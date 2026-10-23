"""Lifecycle of managed Hermes containers (docs/TARGET_ARCHITECTURE.md §9-§11).

One container per customer:
  name    staffbot-hermes-<client_id>
  volume  staffbot-hermes-<client_id>  -> /opt/data   (HERMES_HOME: all customer state)
  managed <HERMES_MANAGED_DIR>/<client_id>/{config.yaml,.env} -> /etc/hermes/* (read-only)
  network CUSTOMER_NETWORK (inter-container traffic disabled)
  API     container 8642 published on CUSTOMER_GATEWAY_IP:<random> for the channel router

Program and data are separate: upgrading swaps the image, the volume stays.

Run the periodic worker (idle sleep + daily backups) with:
    python -m app.services.hermes_orchestrator worker
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm_proxy.routing import RoutingError, managed_route
from app.models.client import Client
from app.models.hermes_instance import HermesInstance
from app.models.package import Package
from app.services import hermes_config
from app.services.audit import log_audit
from app.utils.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)
settings = get_settings()

# Capabilities the upstream image's boot needs before it drops to the hermes
# user (s6: chown of /opt/data, setuid/setgid). Everything else is dropped.
CAPS_KEEP = ["CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE", "FOWNER", "KILL"]
BACKUP_HELPER_IMAGE = "alpine:3.20"


class OrchestratorError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def container_name(client_id: int) -> str:
    return f"staffbot-hermes-{client_id}"


def volume_name(client_id: int) -> str:
    return f"staffbot-hermes-{client_id}"


def _docker():
    import docker
    return docker.from_env()


def ensure_network(dk) -> None:
    import docker
    try:
        dk.networks.get(settings.CUSTOMER_NETWORK)
    except docker.errors.NotFound:
        ipam = docker.types.IPAMConfig(pool_configs=[docker.types.IPAMPool(
            subnet=settings.CUSTOMER_SUBNET, gateway=settings.CUSTOMER_GATEWAY_IP)])
        dk.networks.create(
            settings.CUSTOMER_NETWORK, driver="bridge", ipam=ipam,
            options={"com.docker.network.bridge.enable_icc": "false",
                     "com.docker.network.bridge.name": "sb-customers"},
            labels={"staffbot.type": "customer-network"},
        )


async def _load(db: AsyncSession, client_id: int) -> tuple[Client, Package, Optional[HermesInstance]]:
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if not client:
        raise OrchestratorError(f"client {client_id} not found")
    pkg = (await db.execute(select(Package).where(Package.name == client.package))).scalar_one_or_none()
    if not pkg:
        raise OrchestratorError(f"client {client_id} has no valid package ({client.package})")
    inst = (await db.execute(select(HermesInstance).where(HermesInstance.client_id == client_id))).scalar_one_or_none()
    return client, pkg, inst


def _managed_paths(client_id: int) -> tuple[str, str, str]:
    d = os.path.join(settings.HERMES_MANAGED_DIR, str(client_id))
    return d, os.path.join(d, "config.yaml"), os.path.join(d, ".env")


def write_managed_files(client_id: int, config_yaml: str, env: str) -> None:
    """Root-owned, world-readable (Hermes runs as uid 10000 and must read them)."""
    d, cfg_path, env_path = _managed_paths(client_id)
    os.makedirs(d, mode=0o755, exist_ok=True)
    for path, content in ((cfg_path, config_yaml), (env_path, env)):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)


async def _default_model(db: AsyncSession, pkg: Package) -> str:
    try:
        return (await managed_route(db, pkg, "")).model
    except RoutingError:
        return "default"


async def render_and_write(db: AsyncSession, client: Client, pkg: Package, api_key: Optional[str]) -> str:
    cfg, env, key = hermes_config.render_managed_scope(client, pkg, await _default_model(db, pkg), api_key)
    write_managed_files(client.id, cfg, env)
    return key


def _run_kwargs(client_id: int, pkg: Package, image: str) -> dict:
    _, cfg_path, env_path = _managed_paths(client_id)
    kwargs = dict(
        image=image,
        name=container_name(client_id),
        command=["gateway", "run"],
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        network=settings.CUSTOMER_NETWORK,
        ports={f"{hermes_config.API_SERVER_PORT}/tcp": (settings.CUSTOMER_GATEWAY_IP, None)},
        volumes={
            volume_name(client_id): {"bind": "/opt/data", "mode": "rw"},
            cfg_path: {"bind": "/etc/hermes/config.yaml", "mode": "ro"},
            env_path: {"bind": "/etc/hermes/.env", "mode": "ro"},
        },
        environment={"HERMES_MANAGED_DIR": "/etc/hermes"},
        labels={"staffbot.type": "hermes", "staffbot.client_id": str(client_id)},
        cap_drop=["ALL"],
        cap_add=CAPS_KEEP,
        security_opt=["no-new-privileges:true"],
        mem_limit=f"{max(pkg.memory_limit_mb or 1024, 512)}m",
        memswap_limit=f"{max(pkg.memory_limit_mb or 1024, 512)}m",
        nano_cpus=int(max(pkg.cpu_limit or 0.5, 0.25) * 1e9),
        pids_limit=settings.HERMES_PIDS_LIMIT,
        shm_size="1g" if (pkg.catalog_tier or "basic") == "all" else "64m",  # Chromium needs /dev/shm
    )
    if settings.HERMES_RUNTIME:
        kwargs["runtime"] = settings.HERMES_RUNTIME
    return kwargs


def _published_port(container) -> Optional[int]:
    container.reload()
    bindings = (container.attrs.get("NetworkSettings", {}).get("Ports") or {}).get(
        f"{hermes_config.API_SERVER_PORT}/tcp") or []
    return int(bindings[0]["HostPort"]) if bindings else None


async def _wait_healthy(port: int, key: str) -> bool:
    url = f"http://{settings.CUSTOMER_GATEWAY_IP}:{port}/health"
    deadline = asyncio.get_event_loop().time() + settings.HERMES_WAKE_TIMEOUT
    async with httpx.AsyncClient(timeout=3.0) as http:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await http.get(url, headers={"Authorization": f"Bearer {key}"})
                if r.status_code < 500:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    return False


async def provision(db: AsyncSession, client_id: int, image: Optional[str] = None, dk=None) -> HermesInstance:
    """Create (or re-create) the customer's container. Idempotent; keeps the volume."""
    import docker
    dk = dk or _docker()
    client, pkg, inst = await _load(db, client_id)
    image = image or (inst.image if inst else settings.HERMES_IMAGE)
    old_key = decrypt_value(inst.api_server_key_encrypted) if inst else None
    key = await render_and_write(db, client, pkg, old_key)

    ensure_network(dk)
    try:
        dk.volumes.get(volume_name(client_id))
    except docker.errors.NotFound:
        dk.volumes.create(volume_name(client_id), labels={"staffbot.client_id": str(client_id)})
    try:
        dk.containers.get(container_name(client_id)).remove(force=True)
    except docker.errors.NotFound:
        pass

    if not inst:
        inst = HermesInstance(client_id=client_id, container_name=container_name(client_id),
                              volume_name=volume_name(client_id), image=image,
                              api_server_key_encrypted=encrypt_value(key))
        db.add(inst)
    inst.image, inst.status, inst.last_error = image, "provisioning", None
    await db.commit()

    try:
        container = dk.containers.run(**_run_kwargs(client_id, pkg, image))
        inst.api_port = _published_port(container)
        inst.status = "running"
        inst.last_active_at = _utcnow()
    except Exception as e:  # docker errors, missing image, bad runtime
        inst.status, inst.last_error = "error", str(e)[:1000]
        await db.commit()
        await log_audit(client_id=client_id, action="hermes_provision", resource=image,
                        detail={"error": str(e)[:300]}, status="failure")
        raise OrchestratorError(f"provision failed for client {client_id}: {e}") from e
    await db.commit()
    await log_audit(client_id=client_id, action="hermes_provision", resource=image, detail={"port": inst.api_port})
    return inst


async def wake(db: AsyncSession, client_id: int, dk=None) -> HermesInstance:
    """Make sure the container runs and its API answers. Provisions if missing."""
    import docker
    dk = dk or _docker()
    _, _, inst = await _load(db, client_id)
    if not inst:
        inst = await provision(db, client_id, dk=dk)
    else:
        try:
            container = dk.containers.get(inst.container_name)
            if container.status != "running":
                container.start()
            inst.api_port = _published_port(container)
            inst.status = "running"
        except docker.errors.NotFound:
            inst = await provision(db, client_id, dk=dk)
    inst.last_active_at = _utcnow()
    await db.commit()
    if not await _wait_healthy(inst.api_port, decrypt_value(inst.api_server_key_encrypted)):
        raise OrchestratorError(f"Hermes for client {client_id} did not become ready")
    return inst


async def sleep(db: AsyncSession, client_id: int, dk=None) -> None:
    import docker
    dk = dk or _docker()
    _, _, inst = await _load(db, client_id)
    if not inst:
        return
    try:
        dk.containers.get(inst.container_name).stop(timeout=30)
    except docker.errors.NotFound:
        pass
    inst.status = "sleeping"
    await db.commit()


async def apply_package(db: AsyncSession, client_id: int, dk=None) -> None:
    """Re-render managed config and resource limits after a package change; restarts."""
    dk = dk or _docker()
    client, pkg, inst = await _load(db, client_id)
    if not inst:
        return
    await render_and_write(db, client, pkg, decrypt_value(inst.api_server_key_encrypted))
    await provision(db, client_id, image=inst.image, dk=dk)  # recreate with new limits, same volume


def backup(client_id: int, retention_days: int, dk=None) -> Optional[str]:
    """Snapshot the customer's volume to HERMES_BACKUP_DIR/<id>/<ts>.tar.gz and prune old ones."""
    if retention_days <= 0:
        return None
    dk = dk or _docker()
    host_dir = os.path.join(settings.HERMES_BACKUP_DIR, str(client_id))
    os.makedirs(host_dir, mode=0o700, exist_ok=True)
    name = _utcnow().strftime("%Y%m%dT%H%M%SZ") + ".tar.gz"
    dk.containers.run(
        BACKUP_HELPER_IMAGE, ["tar", "czf", f"/backup/{name}", "-C", "/data", "."],
        volumes={volume_name(client_id): {"bind": "/data", "mode": "ro"}, host_dir: {"bind": "/backup", "mode": "rw"}},
        remove=True, network_disabled=True,
    )
    cutoff = _utcnow() - timedelta(days=retention_days)
    for f in os.listdir(host_dir):
        try:
            ts = datetime.strptime(f.split(".")[0], "%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
        if ts < cutoff:
            os.remove(os.path.join(host_dir, f))
    return os.path.join(host_dir, name)


def write_files_to_volume(client_id: int, files: dict[str, str], dk=None) -> None:
    """Copy text files into the customer's HERMES_HOME volume (paths relative to /opt/data).

    Files are staged on the host and copied by a throwaway helper container, then
    owned by the hermes user (uid 10000) so the agent can manage them.
    """
    import shutil
    dk = dk or _docker()
    stage = os.path.join(settings.HERMES_BACKUP_DIR, "_staging", str(client_id))
    shutil.rmtree(stage, ignore_errors=True)
    for rel, content in files.items():
        if rel.startswith("/") or ".." in rel.split("/"):
            raise OrchestratorError(f"bad path {rel}")
        path = os.path.join(stage, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    top = sorted({rel.split("/")[0] for rel in files})
    script = "cp -r /stage/. /data/ && " + " && ".join(f"chown -R 10000:10000 /data/{t}" for t in top)
    try:
        dk.containers.run(
            BACKUP_HELPER_IMAGE, ["sh", "-c", script],
            volumes={volume_name(client_id): {"bind": "/data", "mode": "rw"}, stage: {"bind": "/stage", "mode": "ro"}},
            remove=True, network_disabled=True,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


async def upgrade(db: AsyncSession, client_id: int, image: str, dk=None) -> HermesInstance:
    """Snapshot, then recreate the container on a new image. Data volume is kept."""
    dk = dk or _docker()
    _, pkg, inst = await _load(db, client_id)
    if not inst:
        raise OrchestratorError(f"client {client_id} has no Hermes instance")
    previous = inst.image
    inst.status = "upgrading"
    await db.commit()
    backup(client_id, max(pkg.backup_retention_days or 0, 1), dk=dk)
    inst.last_backup_at = _utcnow()
    inst = await provision(db, client_id, image=image, dk=dk)
    await log_audit(client_id=client_id, action="hermes_upgrade", resource=image, detail={"from": previous})
    return inst


async def deprovision(db: AsyncSession, client_id: int, keep_volume: bool = True, dk=None) -> None:
    """Remove the container. The volume is kept unless keep_volume=False (after archiving)."""
    import docker
    dk = dk or _docker()
    _, pkg, inst = await _load(db, client_id)
    try:
        dk.containers.get(container_name(client_id)).remove(force=True)
    except docker.errors.NotFound:
        pass
    if not keep_volume:
        backup(client_id, max(pkg.backup_retention_days or 0, 30), dk=dk)
        try:
            dk.volumes.get(volume_name(client_id)).remove(force=True)
        except docker.errors.NotFound:
            pass
    if inst:
        inst.status = "stopped"
        await db.commit()
    await log_audit(client_id=client_id, action="hermes_deprovision", detail={"keep_volume": keep_volume})


async def touch(db: AsyncSession, client_id: int) -> None:
    inst = (await db.execute(select(HermesInstance).where(HermesInstance.client_id == client_id))).scalar_one_or_none()
    if inst:
        inst.last_active_at = _utcnow()
        await db.commit()


async def reap_idle(db: AsyncSession, dk=None) -> list[int]:
    """Put containers to sleep after the package's idle_sleep_minutes (0 = always on)."""
    dk = dk or _docker()
    rows = (await db.execute(
        select(HermesInstance, Package)
        .join(Client, Client.id == HermesInstance.client_id)
        .join(Package, Package.name == Client.package)
        .where(HermesInstance.status == "running")
    )).all()
    slept = []
    now = _utcnow()
    for inst, pkg in rows:
        idle = pkg.idle_sleep_minutes if pkg.idle_sleep_minutes is not None else 30
        if idle > 0 and inst.last_active_at and now - inst.last_active_at > timedelta(minutes=idle):
            await sleep(db, inst.client_id, dk=dk)
            slept.append(inst.client_id)
    return slept


async def daily_backups(db: AsyncSession, dk=None) -> list[int]:
    dk = dk or _docker()
    rows = (await db.execute(
        select(HermesInstance, Package)
        .join(Client, Client.id == HermesInstance.client_id)
        .join(Package, Package.name == Client.package)
        .where(HermesInstance.status.in_(["running", "sleeping"]))
    )).all()
    done = []
    now = _utcnow()
    for inst, pkg in rows:
        if (pkg.backup_retention_days or 0) <= 0:
            continue
        if inst.last_backup_at and now - inst.last_backup_at < timedelta(hours=24):
            continue
        try:
            await asyncio.to_thread(backup, inst.client_id, pkg.backup_retention_days, dk)
            inst.last_backup_at = now
            await db.commit()
            done.append(inst.client_id)
        except Exception as e:
            logger.warning("backup failed for client %s: %s", inst.client_id, e)
    return done


async def _worker_loop(interval: int = 60) -> None:
    from app.database import async_session_factory
    while True:
        try:
            async with async_session_factory() as db:
                slept = await reap_idle(db)
                backed = await daily_backups(db)
                if slept or backed:
                    logger.info("worker: slept=%s backed_up=%s", slept, backed)
        except Exception:
            logger.exception("orchestrator worker iteration failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["worker"]:
        asyncio.run(_worker_loop())
    else:
        print("usage: python -m app.services.hermes_orchestrator worker")
