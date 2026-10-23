"""Admin packages router — CRUD for pricing packages with skill/tool categories."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Optional

import os
from app.database import get_db
from app.services.gateway_config_service import sync_client_quota
from app.models.client import Client
from app.models.package import Package
from app.models.llm_provider import PackageProvider
from app.schemas.admin import PackageCreate, PackageUpdate
from app.middleware.auth import get_current_admin

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[dict])
async def list_packages(
    db: AsyncSession = Depends(get_db),
):
    """List all active packages (public)."""
    result = await db.execute(
        select(Package).where(Package.is_active == True).order_by(Package.sort_order)
    )
    packages = result.scalars().all()
    return [_pkg_to_dict(p) for p in packages]


@router.get("/all", response_model=list[dict])
async def list_all_packages(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all packages including inactive (admin only)."""
    result = await db.execute(
        select(Package).order_by(Package.sort_order)
    )
    packages = result.scalars().all()
    return [_pkg_to_dict(p, admin=True) for p in packages]


@router.get("/categories", response_model=dict)
async def list_categories(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List skill categories from DB with individual skills. Tool categories from DB tool_categories."""
    import re

    # ── Skills: query from skills_registry with individual names ──
    result = await db.execute(
        text("SELECT display_category, name FROM skills_registry WHERE category NOT LIKE '.archive%' AND display_category IS NOT NULL ORDER BY display_category, name")
    )
    skill_rows = result.fetchall()
    skill_cats = {}
    for dc, name in skill_rows:
        if dc not in skill_cats:
            skill_cats[dc] = {"name": dc, "display_name": dc, "count": 0, "skills": []}
        skill_cats[dc]["skills"].append(name)
        skill_cats[dc]["count"] += 1
    skill_categories = sorted(skill_cats.values(), key=lambda x: -x["count"])

    # ── Tools: query from tool_categories DB table ──
    tool_result = await db.execute(
        text("SELECT id, name, display_name, icon FROM tool_categories WHERE is_active = true ORDER BY sort_order")
    )
    tool_rows = tool_result.fetchall()
    tool_categories = []
    for tid, tname, tdisplay, ticon in tool_rows:
        tool_categories.append({
            "name": tname,
            "display_name": tdisplay or tname.replace("-", " ").title(),
            "count": 1,
            "icon": ticon or "",
            "tools": [{"id": tname, "name": tdisplay or tname}],
        })

    return {
        "skill_categories": skill_categories,
        "tool_categories": tool_categories,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_package(
    data: PackageCreate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new package."""
    values = data.model_dump()
    existing = await db.execute(select(Package).where(Package.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Package '{data.name}' already exists")
    pkg = Package(**values, is_active=True)
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return {"message": f"Package '{pkg.name}' created", "id": pkg.id}


@router.put("/{package_id}")
async def update_package(
    package_id: int,
    data: PackageUpdate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a package."""
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    update_data = data.model_dump(exclude_none=True)
    old_tokens = pkg.managed_tokens
    for key, value in update_data.items():
        if key != "id":
            setattr(pkg, key, value)

    await db.flush()

    # If managed_tokens changed, sync all active subscriptions for this package
    if 'managed_tokens' in update_data and update_data['managed_tokens'] != old_tokens:
        from app.models.subscription import Subscription
        from sqlalchemy import update as sqla_update
        result = await db.execute(
            sqla_update(Subscription)
            .where(Subscription.package == pkg.name)
            .values(managed_token_quota=update_data['managed_tokens'])

        )
        synced = result.rowcount
        logger.info(f"Package '{pkg.name}' token quota changed: {old_tokens} → {update_data['managed_tokens']} — synced {synced} subscriptions")

        # Hot-reload gateway profiles for all affected users (no restart needed)
        if synced > 0:
            try:
                # Fetch affected client IDs
                subs_result = await db.execute(
                    select(Subscription.client_id).where(Subscription.package == pkg.name)
                )
                affected_ids = [row[0] for row in subs_result.fetchall()]
                if affected_ids:
                    import httpx
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.put(
                            "http://staffbot-gateway:8080/admin/reload-profile/batch",
                            json=affected_ids,
                        )
                    logger.info(f"Gateway batch reloaded {len(affected_ids)} profiles for package '{pkg.name}'")
            except Exception as e:
                logger.warning(f"Gateway batch reload skipped for package '{pkg.name}': {e}")

    await db.commit()
    return {"message": f"Package '{pkg.name}' updated"}


@router.post("/{package_id}/apply")
async def apply_package_resources(
    package_id: int,
    background: BackgroundTasks,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply this package's limits and Hermes settings to its customers' containers.

    Each managed Hermes container gets a re-rendered managed config and is
    recreated with the new CPU/RAM limits (same data volume), one after another.
    """
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    from app.models.hermes_instance import HermesInstance
    client_ids = [cid for (cid,) in (await db.execute(
        select(HermesInstance.client_id)
        .join(Client, Client.id == HermesInstance.client_id)
        .where(Client.package == pkg.name, HermesInstance.status.in_(["running", "sleeping"]))
        .order_by(HermesInstance.client_id)
    )).all()]
    background.add_task(_apply_to_clients, client_ids)
    return {
        "message": f"Applying {pkg.display_name or pkg.name} to {len(client_ids)} customer container(s)",
        "client_ids": client_ids,
    }


async def _apply_to_clients(client_ids: list[int]) -> None:
    from app.database import async_session_factory
    from app.services import hermes_orchestrator as orch
    for cid in client_ids:
        async with async_session_factory() as db:
            try:
                await orch.apply_package(db, cid)
            except Exception as e:
                logger.warning("apply_package failed for client %s: %s", cid, e)


@router.delete("/{package_id}")
async def delete_package(
    package_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a package and its provider assignments.

    Refused while any client is on the package: deactivate it instead
    (PUT is_active=false) so existing customers keep their plan.
    """
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    from sqlalchemy import func
    in_use = (await db.execute(
        select(func.count()).select_from(Client).where(Client.package == pkg.name)
    )).scalar_one()
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Package '{pkg.name}' is used by {in_use} client(s). Deactivate it instead of deleting.",
        )

    # Delete package-provider assignments first (FK constraint)
    from sqlalchemy import delete as sqla_delete
    await db.execute(sqla_delete(PackageProvider).where(PackageProvider.package_id == package_id))

    name = pkg.name
    await db.delete(pkg)
    await db.commit()
    return {"message": f"Package '{name}' permanently deleted"}


# ── Helpers ────────────────────────────────────────────

def _pkg_to_dict(pkg: Package, admin: bool = False) -> dict:
    """Convert Package to dict with all fields."""
    data = {
        "id": pkg.id,
        "name": pkg.name,
        "display_name": pkg.display_name,
        "price_monthly": pkg.price_monthly,
        "price_yearly": pkg.price_yearly,
        "description": pkg.description,
        "features": pkg.features or [],
        "bot_limit": pkg.bot_limit,
        "sub_ejen_limit": pkg.sub_ejen_limit or 0,
        "managed_tokens": pkg.managed_tokens,
        "cpu_limit": pkg.cpu_limit or 1.0,
        "memory_limit_mb": pkg.memory_limit_mb or 512,
        "storage_limit_gb": pkg.storage_limit_gb or 10,
        "memory_retention_days": pkg.memory_retention_days if pkg.memory_retention_days is not None else 7,
        "memory_item_limit": pkg.memory_item_limit if pkg.memory_item_limit is not None else 50,
        "skill_category_ids": pkg.skill_category_ids or [],
        "tool_category_ids": pkg.tool_category_ids or [],
        "allowed_skill_categories": pkg.allowed_skill_categories or [],
        "allowed_tool_categories": pkg.allowed_tool_categories or [],
        "enabled_skills": pkg.enabled_skills or [],
        "enabled_tools": pkg.enabled_tools or [],
        "knowledge_item_limit": pkg.knowledge_item_limit if pkg.knowledge_item_limit is not None else 50,
        "trial_days": pkg.trial_days or 0,
        "allowed_models": pkg.allowed_models or [],
        "channel_limits": pkg.channel_limits or {},
        "byok_allowed": pkg.byok_allowed if pkg.byok_allowed is not None else True,
        "console_mode": pkg.console_mode or "none",
        "agent_terminal": bool(pkg.agent_terminal),
        "catalog_tier": pkg.catalog_tier or "basic",
        "custom_code_allowed": bool(pkg.custom_code_allowed),
        "idle_sleep_minutes": pkg.idle_sleep_minutes if pkg.idle_sleep_minutes is not None else 30,  # 0 = always on
        "backup_retention_days": pkg.backup_retention_days if pkg.backup_retention_days is not None else 7,
        "upgrade_window": bool(pkg.upgrade_window),
        "support_level": pkg.support_level or "email",
    }
    if admin:
        data.update({
            "sort_order": pkg.sort_order,
            "is_active": pkg.is_active,
            "trial_days": pkg.trial_days or 0,
            "badge": pkg.badge,
            "is_public": pkg.is_public if pkg.is_public is not None else True,
            "badge": pkg.badge,
        })
    return data

# Public endpoints (no auth required)
public_router = APIRouter()

@public_router.get("/public")
async def get_public_packages(
    db: AsyncSession = Depends(get_db),
):
    """Get public packages — no auth required. Used by landing page."""
    result = await db.execute(
        select(Package).where(Package.is_public == True, Package.is_active == True).order_by(Package.sort_order)
    )
    packages = result.scalars().all()
    data = []
    for pkg in packages:
        data.append({
            "id": pkg.id,
            "name": pkg.name,
            "display_name": pkg.display_name or pkg.name,
            "price_monthly": pkg.price_monthly,
            "price_yearly": pkg.price_yearly,
            "description": pkg.description or "",
            "features": pkg.features or [],
            "bot_limit": pkg.bot_limit,
            "sub_ejen_limit": pkg.sub_ejen_limit,
            "managed_tokens": pkg.managed_tokens,
            "cpu_limit": pkg.cpu_limit,
            "memory_limit_mb": pkg.memory_limit_mb,
            "storage_limit_gb": pkg.storage_limit_gb,
            "skill_category_ids": pkg.skill_category_ids or [],
            "tool_category_ids": pkg.tool_category_ids or [],
            "allowed_skill_categories": pkg.allowed_skill_categories or [],
            "allowed_tool_categories": pkg.allowed_tool_categories or [],
        "allowed_skill_categories": pkg.allowed_skill_categories or [],
        "allowed_tool_categories": pkg.allowed_tool_categories or [],
            "trial_days": pkg.trial_days or 0,
            "badge": pkg.badge,
            "sort_order": pkg.sort_order,
        })
    return data
