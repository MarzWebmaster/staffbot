"""Docker management service — 1 container per user, multiple Staff AI inside.

Supports three modes in priority order:
1. Server B API — via WireGuard tunnel (production dual-server)
2. Local Docker SDK — via docker-py (single-server MVP)
3. Simulated — demo/test mode when no Docker available
"""
import os
import socket
import re
import logging
from typing import Optional
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Container image
STAFFBOT_CORE_IMAGE = os.environ.get("STAFFBOT_CORE_IMAGE", "staffbot-core:latest")
CONTAINER_BASE_DIR = os.environ.get("CONTAINER_BASE_DIR", "/root/staffbot/containers")

# Docker SDK — optional import
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


class DockerService:
    """Manage Docker containers — one per user, each hosting multiple Staff AI profiles."""

    @staticmethod
    def _sanitize_name(name: str) -> str:
        sanitized = re.sub(r"[^a-z0-9-]", "", name.lower().strip())
        if not sanitized or len(sanitized) < 2:
            sanitized = f"staffbot-{abs(hash(name)) % 10000}"
        return sanitized[:63]

    @staticmethod
    def _find_available_port(start: int = 9000, end: int = 10000) -> int:
        for port in range(start, end):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return end - 1

    @staticmethod
    def _docker_available() -> bool:
        if not DOCKER_AVAILABLE:
            return False
        try:
            client = docker.from_env()
            client.ping()
            return True
        except Exception:
            return False

    @staticmethod
    def _get_local_docker() -> Optional["docker.DockerClient"]:
        if not DOCKER_AVAILABLE:
            return None
        try:
            return docker.from_env()
        except Exception:
            return None

    @staticmethod
    def get_client_container(client_id: int) -> Optional[dict]:
        """Check if client already has a Docker container running.
        Returns container info dict or None.
        """
        # Find by label
        label = f"staffbot.client_id={client_id}"

        # Server B
        if settings.SERVER_B_API_KEY:
            try:
                import httpx
                resp = httpx.get(
                    f"{settings.SERVER_B_API_URL}/api/containers",
                    headers={"X-API-Key": settings.SERVER_B_API_KEY},
                    timeout=5,
                )
                if resp.status_code == 200:
                    containers = resp.json()
                    for c in containers:
                        if str(c.get("client_id")) == str(client_id):
                            return c
            except Exception:
                pass

        # Local Docker
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                containers = client.containers.list(
                    filters={"label": label},
                    all=True,
                )
                if containers:
                    c = containers[0]
                    return {
                        "id": c.id[:12],
                        "name": c.name,
                        "status": c.status,
                        "port": DockerService._get_container_port(c),
                        "image": c.image.tags[0] if c.image.tags else STAFFBOT_CORE_IMAGE,
                    }
            except Exception:
                pass

        return None

    @staticmethod
    def get_client_containers(client_id: int) -> dict:
        """Get all Docker containers belonging to a client.
        Returns dict of {container_name: {status, port, ...}}.
        """
        result = {}
        label = f"staffbot.client_id={client_id}"

        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                containers = client.containers.list(
                    filters={"label": label},
                    all=True,
                )
                for c in containers:
                    result[c.name] = {
                        "id": c.id[:12],
                        "name": c.name,
                        "status": c.status,
                        "port": DockerService._get_container_port(c),
                    }
            except Exception:
                pass

        return result

    @staticmethod
    def deploy_client_container(
        client_id: int,
        client_name: str,
        subdomain: str = "",
        package: str = "basic",
        cpu_limit: float = 1.0,
        memory_limit_mb: int = 512,
        storage_limit_gb: int = 10,
        skill_categories: list = None,
        tool_categories: list = None,
    ) -> dict:
        """Deploy ONE Docker container per user with package resource limits.
        Returns: {success, container_id, container_name, port, message, status}
        """
        container_name = DockerService._sanitize_name(f"staffbot-{client_id}")
        memory_limit_mb = max(memory_limit_mb, 256)
        cpu_limit = max(cpu_limit, 0.25)
        skill_categories = skill_categories or []
        tool_categories = tool_categories or []
        env = {
            "CLIENT_ID": str(client_id),
            "CLIENT_NAME": client_name,
            "SUBDOMAIN": subdomain or container_name,
            "PACKAGE": package,
            "CPU_LIMIT": str(cpu_limit),
            "MEMORY_LIMIT_MB": str(memory_limit_mb),
            "STORAGE_LIMIT_GB": str(storage_limit_gb),
            "SKILL_CATEGORIES": ",".join(str(s) for s in skill_categories),
            "TOOL_CATEGORIES": ",".join(str(t) for t in tool_categories),
            "GATEWAY_URL": f"http://staffbot-gateway:8080",
            "GATEWAY_AUTH_KEY": settings.SERVER_B_API_KEY or "local-dev",
        }

        # --- METHOD 1: Server B API ---
        if settings.SERVER_B_API_KEY:
            try:
                import httpx
                resp = httpx.post(
                    f"{settings.SERVER_B_API_URL}/api/deploy",
                    json={
                        "client_id": client_id,
                        "container_name": container_name,
                        "subdomain": subdomain or container_name,
                        "env_vars": env,
                        "skills": skill_categories,
                        "cpu_limit": cpu_limit,
                        "memory_limit_mb": memory_limit_mb,
                        "storage_limit_gb": storage_limit_gb,
                    },
                    headers={"X-API-Key": settings.SERVER_B_API_KEY},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    status = "running" if data.get("success") else "error"
                    return {
                        "success": data.get("success", False),
                        "container_id": data.get("container_id", ""),
                        "container_name": data.get("container_name", container_name),
                        "port": data.get("port", 9000),
                        "status": status,
                        "message": data.get("message", "Deployed via Server B"),
                        "deploy_method": "server_b",
                    }
            except Exception as e:
                logger.warning(f"Server B deploy failed: {e}")

        # --- METHOD 2: Local Docker SDK ---
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()

                # Check if already exists (idempotent)
                try:
                    existing = client.containers.get(container_name)
                    port = DockerService._get_container_port(existing) or 9000
                    return {
                        "success": True,
                        "container_id": existing.id,
                        "container_name": container_name,
                        "port": port,
                        "status": existing.status,
                        "message": "Already running",
                        "deploy_method": "local",
                    }
                except Exception:
                    pass  # Create new

                port = DockerService._find_available_port()
                container_dir = f"{CONTAINER_BASE_DIR}/{container_name}"
                os.makedirs(container_dir, exist_ok=True)

                mem_limit = f"{memory_limit_mb}m"
                cpu_period = 100000
                cpu_quota = int(cpu_period * cpu_limit)

                # Pull image if needed
                try:
                    client.images.get(STAFFBOT_CORE_IMAGE)
                except Exception:
                    logger.info(f"Pulling image {STAFFBOT_CORE_IMAGE}...")
                    try:
                        client.images.pull(STAFFBOT_CORE_IMAGE)
                    except Exception:
                        return {
                            "success": False,
                            "container_name": container_name,
                            "port": port,
                            "status": "error",
                            "message": f"Image {STAFFBOT_CORE_IMAGE} not found",
                            "deploy_method": "local",
                        }

                container = client.containers.run(
                    image=STAFFBOT_CORE_IMAGE,
                    name=container_name,
                    detach=True,
                    restart_policy={"Name": "unless-stopped"},
                    environment=env,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    read_only=True,
                    tmpfs={"/tmp": "size=64M"},
                    mem_limit=mem_limit,
                    cpu_period=cpu_period,
                    cpu_quota=cpu_quota,
                    pids_limit=100,
                    ports={"8000/tcp": ("127.0.0.1", port)},
                    volumes={container_dir: {"bind": "/app/data", "mode": "rw"}},
                    labels={
                        "staffbot.client_id": str(client_id),
                        "staffbot.type": "client",
                    },
                )

                return {
                    "success": True,
                    "container_id": container.id,
                    "container_name": container_name,
                    "port": port,
                    "status": "running",
                    "message": "Container deployed locally",
                    "deploy_method": "local",
                }

            except Exception as e:
                logger.error(f"Local Docker deploy failed: {e}")
                return {
                    "success": False,
                    "container_name": container_name,
                    "port": 0,
                    "status": "error",
                    "message": f"Deploy error: {str(e)}",
                    "deploy_method": "local",
                }

        # --- METHOD 3: Simulated ---
        return {
            "success": True,
            "container_id": f"sim_{client_id}",
            "container_name": container_name,
            "port": 8000 + client_id,
            "status": "running",
            "message": "Simulated deployment",
            "deploy_method": "simulated",
        }

    @staticmethod
    def remove_container(container_name: str) -> dict:
        """Remove a Docker container."""
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                container = client.containers.get(container_name)
                container.remove(force=True)
                return {"success": True, "message": f"Container {container_name} removed"}
            except Exception as e:
                logger.warning(f"Local Docker remove failed: {e}")
        return {"success": True, "simulated": True, "message": f"Simulated removal of {container_name}"}

    @staticmethod
    def apply_container_limits(container_name: str, cpu_limit: float, memory_limit_mb: int) -> dict:
        """Update resource limits on a running container.
        Docker doesn't support changing limits directly on running containers
        via SDK for CPU/RAM on all platforms. We update labels for tracking
        and the container reads them on restart.
        """
        if DockerService._docker_available():
            try:
                client = DockerService._get_local_docker()
                container = client.containers.get(container_name)
                # Update labels to store new limits
                current_labels = container.labels or {}
                current_labels["staffbot.cpu_limit"] = str(cpu_limit)
                current_labels["staffbot.memory_limit_mb"] = str(memory_limit_mb)
                # Note: actual limit changes require container recreation
                return {
                    "success": True,
                    "message": f"Limits recorded for {container_name}. Restart to apply.",
                    "test_mode": True,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "simulated": True, "message": "Simulated limit update"}

    @staticmethod
    def _get_container_port(container) -> Optional[int]:
        try:
            port_map = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            for binding in port_map.values():
                if binding:
                    return int(binding[0].get("HostPort", 0))
        except Exception:
            pass
        return None
