"""Admin packages router — CRUD for pricing packages with skill/tool categories."""
from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.docker_service import DockerService

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
    pkg = Package(
        name=data.name,
        display_name=data.display_name,
        price_monthly=data.price_monthly,
        price_yearly=data.price_yearly,
        description=data.description,
        features=data.features,
        bot_limit=data.bot_limit,
        sub_ejen_limit=data.sub_ejen_limit,
        managed_tokens=data.managed_tokens,
        cpu_limit=data.cpu_limit,
        memory_limit_mb=data.memory_limit_mb,
        storage_limit_gb=data.storage_limit_gb,
        memory_retention_days=data.memory_retention_days,
        memory_item_limit=data.memory_item_limit,
        skill_category_ids=data.skill_category_ids,
        tool_category_ids=data.tool_category_ids,
        allowed_skill_categories=data.allowed_skill_categories,
        allowed_tool_categories=data.allowed_tool_categories,
        enabled_skills=data.enabled_skills,
        enabled_tools=data.enabled_tools,
        sort_order=data.sort_order,
        is_active=True,
        trial_days=data.trial_days,
        is_public=data.is_public,
        badge=data.badge,
    )
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
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply CPU/RAM limits to all running containers with this package."""
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    cpu_limit = pkg.cpu_limit or 1.0
    ram_mb = pkg.memory_limit_mb or 512
    storage_gb = pkg.storage_limit_gb or 10

    # Find clients with this package
    from app.models.client import Client
    clients_result = await db.execute(
        select(Client).where(Client.package == pkg.name, Client.status == "active")
    )
    clients_with_pkg = clients_result.scalars().all()

    updated_cpu_ram = []
    storage_warnings = []

    docker = DockerService()

    for cl in clients_with_pkg:
        try:
            # Find their container
            container_info = docker.get_client_container(cl.id)
            if not container_info:
                storage_warnings.append({
                    "client_id": cl.id,
                    "client_name": cl.name,
                    "warning": "No running container found",
                })
                continue

            container_name = container_info.get("name", "")
            if not container_name:
                storage_warnings.append({
                    "client_id": cl.id,
                    "client_name": cl.name,
                    "warning": "Container name not found",
                })
                continue

            # Apply limits
            apply_result = docker.apply_container_limits(
                container_name=container_name,
                cpu_limit=cpu_limit,
                memory_limit_mb=ram_mb,
            )

            updated_cpu_ram.append({
                "client_id": cl.id,
                "client_name": cl.name,
                "container_name": container_name,
                "result": apply_result,
            })

            # Storage warnings (requires recreation)
            storage_warnings.append({
                "client_id": cl.id,
                "client_name": cl.name,
                "container_name": container_name,
                "warning": f"Storage change to {storage_gb}GB requires container recreation",
            })

        except Exception as e:
            storage_warnings.append({
                "client_id": cl.id,
                "client_name": cl.name,
                "error": str(e),
            })

    return {
        "message": f"Applied limits for {pkg.display_name or pkg.name}",
        "new_limits": {
            "cpu": cpu_limit,
            "ram_mb": ram_mb,
            "storage_gb": storage_gb,
        },
        "updated_cpu_ram": updated_cpu_ram,
        "storage_warnings": storage_warnings,
    }


@router.delete("/{package_id}")
async def delete_package(
    package_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a package and its provider assignments."""
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

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
