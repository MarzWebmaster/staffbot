"""Seed the v1 package proposal (docs/TARGET_ARCHITECTURE.md §7).

Dry-run by default; prints what would change. Existing packages are only
updated with --apply --overwrite, so prices a superadmin already set are kept.

    python -m scripts.seed_packages_v1            # dry run
    python -m scripts.seed_packages_v1 --apply    # insert missing packages
    python -m scripts.seed_packages_v1 --apply --overwrite
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import async_session_factory
from app.models.package import Package

PACKAGES = [
    dict(name="trial", display_name="Percubaan", price_monthly=0, trial_days=7, sort_order=0,
         bot_limit=1, managed_tokens=200_000, allowed_models=[], byok_allowed=False,
         channel_limits={"web": True, "whatsapp": 0, "telegram": 0},
         console_mode="none", agent_terminal=False, catalog_tier="basic", custom_code_allowed=False,
         cpu_limit=0.5, memory_limit_mb=1024, storage_limit_gb=2,
         idle_sleep_minutes=15, backup_retention_days=0, upgrade_window=False, support_level="none",
         is_public=True),
    dict(name="starter", display_name="Starter", price_monthly=49, price_yearly=499, sort_order=1,
         bot_limit=1, managed_tokens=2_000_000, allowed_models=[], byok_allowed=True,
         channel_limits={"web": True, "whatsapp": 1, "telegram": 1},
         console_mode="hermes", agent_terminal=False, catalog_tier="basic", custom_code_allowed=False,
         cpu_limit=0.5, memory_limit_mb=1024, storage_limit_gb=5,
         idle_sleep_minutes=30, backup_retention_days=7, upgrade_window=False, support_level="email",
         is_public=True),
    dict(name="professional", display_name="Professional", price_monthly=149, price_yearly=1499, sort_order=2,
         bot_limit=3, managed_tokens=8_000_000, allowed_models=[], byok_allowed=True,
         channel_limits={"web": True, "whatsapp": 2, "telegram": 1},
         console_mode="shell", agent_terminal=True, catalog_tier="all", custom_code_allowed=True,
         cpu_limit=1.0, memory_limit_mb=2048, storage_limit_gb=20,
         idle_sleep_minutes=60, backup_retention_days=14, upgrade_window=False, support_level="email_whatsapp",
         badge="popular", is_public=True),
    dict(name="enterprise", display_name="Enterprise", price_monthly=499, price_yearly=4999, sort_order=3,
         bot_limit=10, managed_tokens=30_000_000, allowed_models=["*"], byok_allowed=True,
         channel_limits={"web": True, "whatsapp": 5, "telegram": 1},
         console_mode="shell", agent_terminal=True, catalog_tier="all", custom_code_allowed=True,
         cpu_limit=2.0, memory_limit_mb=4096, storage_limit_gb=50,
         idle_sleep_minutes=0, backup_retention_days=30, upgrade_window=True, support_level="priority",
         is_public=True),
]


async def main(apply: bool, overwrite: bool) -> None:
    async with async_session_factory() as db:
        for spec in PACKAGES:
            pkg = (await db.execute(select(Package).where(Package.name == spec["name"]))).scalar_one_or_none()
            if pkg is None:
                print(f"+ create {spec['name']}")
                if apply:
                    db.add(Package(**spec, is_active=True))
            elif overwrite:
                print(f"~ overwrite {spec['name']}")
                if apply:
                    for k, v in spec.items():
                        setattr(pkg, k, v)
            else:
                print(f"= keep {spec['name']} (exists; use --overwrite to replace)")
        if apply:
            await db.commit()
    if not apply:
        print("dry run: nothing written (use --apply)")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv, "--overwrite" in sys.argv))
