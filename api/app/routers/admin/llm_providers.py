"""
Admin LLM Providers router — CRUD for managed LLM providers + package assignments.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.llm_provider import LlmProvider, PackageProvider
from app.models.package import Package
from app.schemas.llm_provider import (
    LlmProviderCreate, LlmProviderUpdate, LlmProviderResponse,
    PackageProviderAssign, PackageProviderResponse,
)
from app.middleware.auth import get_current_admin
from app.utils.encryption import encrypt_value, decrypt_value

router = APIRouter()


# ── LLM Provider CRUD ──────────────────────────────────────────────

@router.get("/providers", response_model=list[LlmProviderResponse])
async def list_providers(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all LLM providers (admin only)."""
    result = await db.execute(
        select(LlmProvider).order_by(LlmProvider.sort_order)
    )
    providers = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "models": p.models or [],
            "default_model": p.default_model,
            "description": p.description,
            "logo_url": p.logo_url,
            "sort_order": p.sort_order,
            "is_active": p.is_active,
            "api_key_configured": bool(p.api_key_encrypted),
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in providers
    ]


@router.get("/providers/active", response_model=list[LlmProviderResponse])
async def list_active_providers(
    db: AsyncSession = Depends(get_db),
):
    """List active LLM providers (public — for checkout/pricing page)."""
    result = await db.execute(
        select(LlmProvider)
        .where(LlmProvider.is_active == True)
        .order_by(LlmProvider.sort_order)
    )
    providers = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "models": p.models or [],
            "default_model": p.default_model,
            "description": p.description,
            "logo_url": p.logo_url,
            "sort_order": p.sort_order,
            "is_active": True,
            "api_key_configured": bool(p.api_key_encrypted),
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in providers
    ]


@router.get("/providers/{provider_id}", response_model=LlmProviderResponse)
async def get_provider(
    provider_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single LLM provider."""
    result = await db.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    return {
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name,
        "base_url": p.base_url,
        "models": p.models or [],
        "default_model": p.default_model,
        "description": p.description,
        "logo_url": p.logo_url,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "api_key_configured": bool(p.api_key_encrypted),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    data: LlmProviderCreate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new LLM provider."""
    # Check for duplicate name
    existing = await db.execute(
        select(LlmProvider).where(LlmProvider.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider '{data.name}' already exists",
        )

    provider = LlmProvider(
        name=data.name,
        display_name=data.display_name,
        base_url=data.base_url,
        api_key_encrypted=encrypt_value(data.api_key) if data.api_key else None,
        models=data.models or [],
        default_model=data.default_model,
        description=data.description,
        logo_url=data.logo_url,
        sort_order=data.sort_order,
        is_active=data.is_active,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return {
        "message": f"Provider '{provider.display_name}' created",
        "id": provider.id,
    }


@router.put("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    data: LlmProviderUpdate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an LLM provider."""
    result = await db.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    update_data = data.model_dump(exclude_none=True)
    if "api_key" in update_data:
        update_data["api_key_encrypted"] = encrypt_value(update_data.pop("api_key"))

    for key, value in update_data.items():
        setattr(p, key, value)

    await db.commit()
    return {"message": f"Provider '{p.display_name}' updated"}


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete an LLM provider and its package assignments."""
    result = await db.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    # Delete package assignments first (FK constraint)
    from sqlalchemy import delete as sqla_delete
    await db.execute(sqla_delete(PackageProvider).where(PackageProvider.provider_id == provider_id))

    name = p.display_name
    await db.delete(p)
    await db.commit()
    return {"message": f"Provider '{name}' permanently deleted"}


# ── Package-Provider Assignments ───────────────────────────────────

@router.get("/package-providers", response_model=list[PackageProviderResponse])
async def list_package_providers(
    package_id: int = None,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all package-provider assignments. Filter by package_id optionally."""
    query = select(PackageProvider)
    if package_id:
        query = query.where(PackageProvider.package_id == package_id)

    result = await db.execute(query)
    items = result.scalars().all()

    # Eager load provider details
    response = []
    for item in items:
        provider_result = await db.execute(
            select(LlmProvider).where(LlmProvider.id == item.provider_id)
        )
        prov = provider_result.scalar_one_or_none()
        response.append({
            "id": item.id,
            "package_id": item.package_id,
            "provider_id": item.provider_id,
            "token_quota": item.token_quota or 0.0,
            "is_available": item.is_available,
            "provider": {
                "id": prov.id,
                "name": prov.name,
                "display_name": prov.display_name,
                "base_url": prov.base_url,
                "models": prov.models or [],
                "default_model": prov.default_model,
                "description": prov.description,
                "logo_url": prov.logo_url,
                "sort_order": prov.sort_order,
                "is_active": prov.is_active,
                "api_key_configured": bool(prov.api_key_encrypted),
                "created_at": prov.created_at,
                "updated_at": prov.updated_at,
            } if prov else None,
        })

    return response


@router.post("/package-providers", status_code=status.HTTP_201_CREATED)
async def assign_provider_to_package(
    data: PackageProviderAssign,
    package_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign a provider to a package."""
    # Verify package exists
    pkg_result = await db.execute(select(Package).where(Package.id == package_id))
    if not pkg_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    # Verify provider exists
    prov_result = await db.execute(select(LlmProvider).where(LlmProvider.id == data.provider_id))
    if not prov_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    # Check for duplicate
    dup = await db.execute(
        select(PackageProvider).where(
            PackageProvider.package_id == package_id,
            PackageProvider.provider_id == data.provider_id,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider already assigned to this package")

    pp = PackageProvider(
        package_id=package_id,
        provider_id=data.provider_id,
        token_quota=data.token_quota,
        is_available=data.is_available,
    )
    db.add(pp)
    await db.commit()
    await db.refresh(pp)
    return {
        "message": "Provider assigned to package",
        "id": pp.id,
    }


@router.put("/package-providers/{assignment_id}")
async def update_package_provider(
    assignment_id: int,
    data: PackageProviderAssign,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a package-provider assignment (token quota, availability)."""
    result = await db.execute(select(PackageProvider).where(PackageProvider.id == assignment_id))
    pp = result.scalar_one_or_none()
    if not pp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    update_data = data.model_dump(exclude_none=True, exclude={"provider_id"})
    for key, value in update_data.items():
        setattr(pp, key, value)

    await db.commit()
    return {"message": "Package-provider assignment updated"}


@router.delete("/package-providers/{assignment_id}")
async def remove_provider_from_package(
    assignment_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove a provider from a package."""
    result = await db.execute(select(PackageProvider).where(PackageProvider.id == assignment_id))
    pp = result.scalar_one_or_none()
    if not pp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    await db.delete(pp)
    await db.commit()
    return {"message": "Provider removed from package"}
