"""Pick the upstream provider, key and model for a customer's request.

Order (docs/TARGET_ARCHITECTURE.md §8):
1. BYOK: the customer's own active key, if the package allows BYOK and the
   key's provider has a known base_url. Any model; no managed quota used.
2. Managed: providers assigned to the package. The requested model must be
   allowed by the package, otherwise the package default model is used.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.llm_provider import LlmProvider, PackageProvider
from app.models.package import Package
from app.utils.encryption import decrypt_value


class RoutingError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Route:
    base_url: str
    api_key: str
    model: str
    provider: str
    key_source: str  # "byok" | "managed"
    requested_model: str

    @property
    def substituted(self) -> bool:
        return self.model != self.requested_model


def _provider_models(p: LlmProvider) -> list[str]:
    models = list(p.models or [])
    if p.default_model and p.default_model not in models:
        models.insert(0, p.default_model)
    return models


async def _byok_route(db: AsyncSession, client_id: int, requested: str) -> Optional[Route]:
    keys = (await db.execute(
        select(ApiKey).where(
            ApiKey.client_id == client_id,
            ApiKey.is_active == True,  # noqa: E712
            ApiKey.is_managed == False,  # noqa: E712
            ApiKey.key_encrypted.isnot(None),
        ).order_by(ApiKey.id)
    )).scalars().all()
    for key in keys:
        provider = (await db.execute(
            select(LlmProvider).where(LlmProvider.name == key.provider)
        )).scalar_one_or_none()
        if not provider or not provider.base_url:
            continue
        try:
            secret = decrypt_value(key.key_encrypted)
        except Exception:
            continue
        model = requested or provider.default_model or ""
        return Route(provider.base_url, secret, model, provider.name, "byok", requested)
    return None


async def managed_route(db: AsyncSession, pkg: Package, requested: str) -> Route:
    assigned = (await db.execute(
        select(LlmProvider)
        .join(PackageProvider, PackageProvider.provider_id == LlmProvider.id)
        .where(
            PackageProvider.package_id == pkg.id,
            PackageProvider.is_available == True,  # noqa: E712
            LlmProvider.is_active == True,  # noqa: E712
            LlmProvider.api_key_encrypted.isnot(None),
        )
        .order_by(LlmProvider.sort_order, LlmProvider.id)
    )).scalars().all()
    if not assigned:
        raise RoutingError(503, "no_provider", "No LLM provider is assigned to your package. Contact support.")

    allowed = list(pkg.allowed_models or [])
    if "*" in allowed:
        candidates = (await db.execute(
            select(LlmProvider).where(
                LlmProvider.is_active == True,  # noqa: E712
                LlmProvider.api_key_encrypted.isnot(None),
            ).order_by(LlmProvider.sort_order, LlmProvider.id)
        )).scalars().all()
        allowed_set = None  # any model a provider offers
    else:
        candidates = assigned
        allowed_set = set(allowed) if allowed else {m for p in assigned for m in _provider_models(p)}

    chosen, model = None, None
    if requested and (allowed_set is None or requested in allowed_set):
        chosen = next((p for p in candidates if requested in _provider_models(p)), None)
        if chosen:
            model = requested
    if chosen is None:
        # Not allowed or not offered: fall back to the package default model
        chosen = assigned[0]
        defaults = [m for m in _provider_models(chosen) if allowed_set is None or m in allowed_set]
        model = (defaults or _provider_models(chosen) or [requested])[0]

    try:
        secret = decrypt_value(chosen.api_key_encrypted)
    except Exception:
        raise RoutingError(503, "provider_key_error", "Provider key could not be decrypted. Contact support.")
    return Route(chosen.base_url, secret, model, chosen.name, "managed", requested)


async def resolve_route(db: AsyncSession, client_id: int, pkg: Package, requested: str) -> Route:
    if pkg.byok_allowed is not False:
        route = await _byok_route(db, client_id, requested)
        if route:
            return route
    return await managed_route(db, pkg, requested)
