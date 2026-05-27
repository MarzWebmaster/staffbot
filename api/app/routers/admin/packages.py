"""Admin packages router — CRUD for pricing packages with skill/tool categories."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Optional

import os
from app.database import get_db
from app.models.client import Client
from app.models.package import Package
from app.models.llm_provider import PackageProvider
from app.schemas.admin import PackageCreate, PackageUpdate
from app.middleware.auth import get_current_admin
from app.services.docker_service import DockerService

router = APIRouter()


@router.get("/", response_model=list[dict])
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
    """List all skill and tool categories dynamically from BUILTIN_SKILLS/BUILTIN_TOOLSETS."""
    import ast, re

    # Read policy.py to extract BUILTIN_SKILLS and BUILTIN_TOOLSETS
    policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
    if not os.path.exists(policy_path):
        return {"skill_categories": [], "tool_categories": []}

    with open(policy_path, "r") as f:
        policy_content = f.read()

    # Extract BUILTIN_SKILLS section
    skills_start = policy_content.find("BUILTIN_SKILLS = [")
    skills_end = policy_content.find("BUILTIN_TOOLSETS = [")
    skills_section = policy_content[skills_start:skills_end] if skills_start >= 0 else ""

    # Extract skill dicts and group by category
    skill_categories = {}
    if skills_section:
        idx = 0
        while idx < len(skills_section):
            bs = skills_section.find("{", idx)
            if bs == -1: break
            depth = 1; be = bs + 1
            while depth > 0 and be < len(skills_section):
                if skills_section[be] == "{": depth += 1
                elif skills_section[be] == "}": depth -= 1
                be += 1
            d = skills_section[bs:be]
            id_m = re.search(r'"id": "([a-zA-Z0-9_-]+)"', d)
            cat_m = re.search(r'"category": "([a-zA-Z0-9_-]+)"', d)
            name_m = re.search(r'"name": "([^"]+)"', d)
            desc_m = re.search(r'"desc": "([^"]+)"', d)
            if id_m and cat_m:
                cat = cat_m.group(1)
                if cat not in skill_categories:
                    skill_categories[cat] = {"name": cat, "display_name": cat.replace("-", " ").title(), "skills": [], "count": 0}
                skill_categories[cat]["skills"].append({
                    "id": id_m.group(1),
                    "name": name_m.group(1) if name_m else id_m.group(1),
                    "desc": desc_m.group(1) if desc_m else "",
                })
                skill_categories[cat]["count"] += 1
            idx = be

    # Extract BUILTIN_TOOLSETS section
    tools_start = policy_content.find("BUILTIN_TOOLSETS = [")
    tools_end = policy_content.find("DEFAULT_GOVERNANCE_POLICY")
    # Go back 2 chars to exclude the newlines before it
    if tools_end > 2:
        tools_end -= 2
    tools_section = policy_content[tools_start:tools_end] if tools_start >= 0 else ""

    tool_categories = {}
    if tools_section:
        idx = 0
        while idx < len(tools_section):
            bs = tools_section.find("{", idx)
            if bs == -1: break
            depth = 1; be = bs + 1
            while depth > 0 and be < len(tools_section):
                if tools_section[be] == "{": depth += 1
                elif tools_section[be] == "}": depth -= 1
                be += 1
            d = tools_section[bs:be]
            id_m = re.search(r'"id": "([a-zA-Z0-9_-]+)"', d)
            cat_m = re.search(r'"category": "([a-zA-Z0-9_-]+)"', d)
            name_m = re.search(r'"name": "([^"]+)"', d)
            if id_m and cat_m:
                cat = cat_m.group(1)
                if cat not in tool_categories:
                    tool_categories[cat] = {"name": cat, "display_name": cat.replace("-", " ").title(), "tools": [], "count": 0}
                tool_categories[cat]["tools"].append({
                    "id": id_m.group(1),
                    "name": name_m.group(1) if name_m else id_m.group(1),
                })
                tool_categories[cat]["count"] += 1
            idx = be

    return {
        "skill_categories": sorted(skill_categories.values(), key=lambda x: -x["count"]),
        "tool_categories": sorted(tool_categories.values(), key=lambda x: -x["count"]),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
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
        skill_category_ids=data.skill_category_ids,
        tool_category_ids=data.tool_category_ids,
        allowed_skill_categories=data.allowed_skill_categories,
        allowed_tool_categories=data.allowed_tool_categories,
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
    for key, value in update_data.items():
        if key != "id":
            setattr(pkg, key, value)

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
        "skill_category_ids": pkg.skill_category_ids or [],
        "tool_category_ids": pkg.tool_category_ids or [],
        "allowed_skill_categories": pkg.allowed_skill_categories or [],
        "allowed_tool_categories": pkg.allowed_tool_categories or [],
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
