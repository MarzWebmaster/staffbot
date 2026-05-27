"""
LLM Providers user router — endpoints for subscribers to view available
managed providers in their package and per-provider token usage.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.llm_provider import LlmProvider, PackageProvider
from app.middleware.auth import get_current_client

router = APIRouter()


@router.get("/available")
async def get_available_providers(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get managed LLM providers available in the user's current package."""
    # Get user's subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == current_user.id)
    )
    sub = sub_result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription")

    # Find which package matches
    from app.models.package import Package
    pkg_result = await db.execute(
        select(Package).where(Package.name == sub.package)
    )
    pkg = pkg_result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    # Get assigned providers
    pp_result = await db.execute(
        select(PackageProvider).where(
            PackageProvider.package_id == pkg.id,
            PackageProvider.is_available == True,
        )
    )
    assignments = pp_result.scalars().all()

    provider_usage = sub.provider_token_usage or {}

    providers = []
    for pp in assignments:
        prov_result = await db.execute(
            select(LlmProvider).where(
                LlmProvider.id == pp.provider_id,
                LlmProvider.is_active == True,
            )
        )
        prov = prov_result.scalar_one_or_none()
        if not prov:
            continue

        token_used = provider_usage.get(prov.name, 0)
        max_tokens = pp.token_quota if pp.token_quota > 0 else sub.managed_token_quota

        providers.append({
            "id": prov.id,
            "name": prov.name,
            "display_name": prov.display_name,
            "description": prov.description,
            "logo_url": prov.logo_url,
            "models": prov.models or [],
            "default_model": prov.default_model,
            "token_used": token_used,
            "token_quota": max_tokens,
            "token_remaining": max(0, max_tokens - token_used),
        })

    return providers


@router.get("/usage")
async def get_provider_usage(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get per-provider token usage for the current user's subscription."""
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == current_user.id)
    )
    sub = sub_result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription")

    provider_usage = sub.provider_token_usage or {}

    return {
        "total_quota": sub.managed_token_quota,
        "total_used": sub.managed_token_used,
        "per_provider": provider_usage,
    }
