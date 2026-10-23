"""Superadmin: managed Hermes containers and version rollout (docs/TARGET_ARCHITECTURE.md §10)."""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_db
from app.middleware.auth import get_current_admin
from app.models.client import Client
from app.models.hermes_instance import HermesInstance
from app.services import hermes_orchestrator as orch

logger = logging.getLogger(__name__)
router = APIRouter()


def _inst(i: HermesInstance, c: Optional[Client] = None) -> dict:
    return {
        "client_id": i.client_id, "client_name": c.name if c else None, "package": c.package if c else None,
        "container": i.container_name, "image": i.image, "status": i.status, "api_port": i.api_port,
        "last_error": i.last_error,
        "last_active_at": i.last_active_at.isoformat() if i.last_active_at else None,
        "last_backup_at": i.last_backup_at.isoformat() if i.last_backup_at else None,
    }


@router.get("/instances")
async def list_instances(admin: Client = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(HermesInstance, Client).join(Client, Client.id == HermesInstance.client_id).order_by(HermesInstance.client_id)
    )).all()
    return [_inst(i, c) for i, c in rows]


ACTIONS = {"provision", "wake", "sleep", "backup", "apply-package", "deprovision"}


@router.post("/{client_id}/{action}")
async def instance_action(client_id: int, action: str, admin: Client = Depends(get_current_admin),
                          db: AsyncSession = Depends(get_db)):
    if action not in ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown action")
    try:
        if action == "provision":
            await orch.provision(db, client_id)
        elif action == "wake":
            await orch.wake(db, client_id)
        elif action == "sleep":
            await orch.sleep(db, client_id)
        elif action == "apply-package":
            await orch.apply_package(db, client_id)
        elif action == "deprovision":
            await orch.deprovision(db, client_id, keep_volume=True)
        elif action == "backup":
            client, pkg, _ = await orch._load(db, client_id)
            path = await asyncio.to_thread(orch.backup, client_id, max(pkg.backup_retention_days or 0, 1))
            return {"message": "Backup created", "path": path}
    except orch.OrchestratorError as e:
        raise HTTPException(status_code=409, detail=str(e))
    inst = (await db.execute(select(HermesInstance).where(HermesInstance.client_id == client_id))).scalar_one_or_none()
    return _inst(inst) if inst else {"message": f"{action} done"}


class Rollout(BaseModel):
    image: str = Field(..., min_length=3, description="e.g. staffbot-hermes:0.23.0-sb1")
    client_ids: Optional[list[int]] = Field(None, description="Canary: only these customers")
    percent: Optional[int] = Field(None, ge=1, le=100, description="Canary: first N% of customers by id")
    batch_size: int = Field(10, ge=1, le=100)


async def _run_rollout(image: str, client_ids: list[int], batch_size: int) -> None:
    for start in range(0, len(client_ids), batch_size):
        for cid in client_ids[start:start + batch_size]:
            async with async_session_factory() as db:
                try:
                    await orch.upgrade(db, cid, image)
                except Exception as e:  # keep going; failures show as status=error
                    logger.warning("rollout %s failed for client %s: %s", image, cid, e)


@router.post("/rollout")
async def rollout(data: Rollout, background: BackgroundTasks, admin: Client = Depends(get_current_admin),
                  db: AsyncSession = Depends(get_db)):
    """Upgrade customers to a new image: canary (client_ids / percent) or everyone, in batches.

    Each upgrade snapshots the volume first; roll back by running a rollout with the old image.
    """
    ids = [i for (i,) in (await db.execute(
        select(HermesInstance.client_id).where(HermesInstance.image != data.image).order_by(HermesInstance.client_id)
    )).all()]
    if data.client_ids:
        ids = [i for i in ids if i in set(data.client_ids)]
    elif data.percent:
        ids = ids[:max(1, len(ids) * data.percent // 100)]
    background.add_task(_run_rollout, data.image, ids, data.batch_size)
    return {"message": "Rollout started", "image": data.image, "customers": ids, "batch_size": data.batch_size}
