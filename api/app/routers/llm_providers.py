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
from app.models.api_key import ApiKey
from app.schemas.llm_provider import LlmProviderResponse
from app.utils.encryption import encrypt_value, mask_key
from datetime import datetime, timedelta, timezone
from collections import defaultdict

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


@router.get("/byok-status")
async def get_byok_status(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get per-provider BYOK/managed status for current user."""
    from app.models.package import Package

    # Get user subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == current_user.id)
    )
    sub = sub_result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription")

    # Get package
    pkg_result = await db.execute(select(Package).where(Package.name == sub.package))
    pkg = pkg_result.scalar_one_or_none()

    # Get all active providers
    prov_result = await db.execute(
        select(LlmProvider).where(LlmProvider.is_active == True).order_by(LlmProvider.sort_order)
    )
    all_providers = prov_result.scalars().all()

    # Get user's api keys
    key_result = await db.execute(
        select(ApiKey).where(ApiKey.client_id == current_user.id)
    )
    user_keys = key_result.scalars().all()
    byok_map = {k.provider: k for k in user_keys if not k.is_managed}
    managed_map = {k.provider: k for k in user_keys if k.is_managed}

    # Get package-provider assignments
    provider_usage = sub.provider_token_usage or {}

    result = []
    for prov in all_providers:
        # Check if this provider is in user's package as managed
        is_managed = False
        if pkg:
            pp_result = await db.execute(
                select(PackageProvider).where(
                    PackageProvider.package_id == pkg.id,
                    PackageProvider.provider_id == prov.id,
                    PackageProvider.is_available == True,
                )
            )
            pp = pp_result.scalar_one_or_none()
            is_managed = pp is not None

        byok_key = byok_map.get(prov.name)
        has_byok = byok_key is not None and byok_key.is_active
        token_used = provider_usage.get(prov.name, 0)

        result.append({
            "id": prov.id,
            "name": prov.name,
            "display_name": prov.display_name,
            "description": prov.description,
            "logo_url": prov.logo_url,
            "models": prov.models or [],
            "default_model": prov.default_model,
            "is_managed_available": is_managed,
            "has_byok": has_byok,
            "byok_key_prefix": byok_key.key_prefix if byok_key else None,
            "token_used": token_used,
            "managed_token_quota": pp.token_quota if is_managed and pp else 0,
        })

    return result


from pydantic import BaseModel

class BYOKToggleRequest(BaseModel):
    provider_name: str = "openrouter"
    enable: bool = True
    api_key: str = None

@router.post("/toggle-byok")
async def toggle_byok(
    data: BYOKToggleRequest = None,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable BYOK for a specific provider. If enabling and api_key provided, save it."""
    provider_name = data.provider_name if data else "openrouter"
    enable = data.enable if data else True
    api_key = data.api_key if data else None

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.client_id == current_user.id,
            ApiKey.provider == provider_name,
            ApiKey.is_managed == False,
        )
    )
    existing = result.scalar_one_or_none()

    if enable and api_key:
        if existing:
            existing.key_encrypted = encrypt_value(api_key)
            existing.key_prefix = mask_key(api_key)
            existing.is_active = True
        else:
            new_key = ApiKey(
                client_id=current_user.id,
                provider=provider_name,
                key_encrypted=encrypt_value(api_key),
                key_prefix=mask_key(api_key),
                is_active=True,
                is_managed=False,
            )
            db.add(new_key)
    elif not enable:
        if existing:
            existing.is_active = False
    else:
        if existing:
            existing.is_active = not existing.is_active

    await db.commit()
    return {"message": f"BYOK for {provider_name} {'enabled' if enable else 'disabled'}"}


@router.get("/daily-usage")
async def get_daily_token_usage(
    days: int = 30,
    brand: str = None,
    token_type: str = "all",
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get daily token usage chart data. Filter by brand and token type (managed/byok/all)."""
    from app.models.api_key import ApiKey
    from app.models.token_usage import TokenUsageLog

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    range_start = now - timedelta(days=days)

    # Get user's API keys (to know which providers are BYOK vs managed)
    key_result = await db.execute(
        select(ApiKey).where(
            ApiKey.client_id == current_user.id,
            ApiKey.is_active == True,
        )
    )
    user_keys = key_result.scalars().all()
    byok_providers = set(k.provider for k in user_keys if not k.is_managed)

    # Build query
    query = select(TokenUsageLog).where(
        TokenUsageLog.client_id == current_user.id,
        TokenUsageLog.created_at >= range_start,
        TokenUsageLog.created_at <= now,
    )

    if brand:
        query = query.where(TokenUsageLog.provider == brand)

    query = query.order_by(TokenUsageLog.created_at)
    result = await db.execute(query)
    logs = result.scalars().all()

    # Group by day
    buckets = defaultdict(lambda: {"managed_tokens": 0, "byok_tokens": 0, "managed_requests": 0, "byok_requests": 0})

    for log in logs:
        key = log.created_at.strftime("%Y-%m-%d")
        is_byok = log.provider in byok_providers
        if is_byok:
            buckets[key]["byok_tokens"] += log.total_tokens
            buckets[key]["byok_requests"] += 1
        else:
            buckets[key]["managed_tokens"] += log.total_tokens
            buckets[key]["managed_requests"] += 1

    timeseries = []
    for i in range(days):
        d = (range_start + timedelta(days=i)).strftime("%Y-%m-%d")
        b = buckets.get(d, {"managed_tokens": 0, "byok_tokens": 0, "managed_requests": 0, "byok_requests": 0})

        # Apply token_type filter at the series level
        if token_type == "managed":
            entry_total = b["managed_tokens"]
        elif token_type == "byok":
            entry_total = b["byok_tokens"]
        else:
            entry_total = b["managed_tokens"] + b["byok_tokens"]

        if entry_total > 0 or i == len(timeseries) or True:  # always include days
            timeseries.append({
                "date": d,
                "managed_tokens": b["managed_tokens"],
                "byok_tokens": b["byok_tokens"],
                "total_tokens": b["managed_tokens"] + b["byok_tokens"],
                "managed_requests": b["managed_requests"],
                "byok_requests": b["byok_requests"],
            })

    return {"timeseries": timeseries}
