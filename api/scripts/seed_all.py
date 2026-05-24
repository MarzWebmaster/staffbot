#!/usr/bin/env python3
"""Seed all data: packages, provider links, admin user."""
import asyncio, asyncpg, json, hashlib, os, secrets, string
from datetime import datetime

DB_URL = "postgresql://staffbot:staffbot123@db:5432/staffbot_db"

PACKAGES = [
    {
        "name": "starter",
        "display_name": "Starter",
        "price_monthly": 49,
        "price_yearly": 499,
        "description": "Suitable for small businesses just getting started with AI.",
        "features": json.dumps([
            "1 AI Agent",
            "Managed LLM tokens: 100,000/month",
            "WhatsApp integration",
            "Basic support",
        ]),
        "bot_limit": 1,
        "managed_tokens": 100000,
        "sort_order": 1,
        "provider_links": [
            {"provider_name": "ilmu_ai", "token_quota": 100000},
        ],
    },
    {
        "name": "professional",
        "display_name": "Professional",
        "price_monthly": 149,
        "price_yearly": 1499,
        "description": "Perfect for growing businesses that need more power.",
        "features": json.dumps([
            "3 AI Agents",
            "Managed LLM tokens: 500,000/month",
            "WhatsApp + Telegram integration",
            "Google Drive integration",
            "Email integration",
            "Priority support",
        ]),
        "bot_limit": 3,
        "managed_tokens": 500000,
        "sort_order": 2,
        "provider_links": [
            {"provider_name": "ilmu_ai", "token_quota": 250000},
            {"provider_name": "openrouter", "token_quota": 250000},
        ],
    },
    {
        "name": "enterprise",
        "display_name": "Enterprise",
        "price_monthly": 499,
        "price_yearly": 4999,
        "description": "For businesses that demand the best.",
        "features": json.dumps([
            "10 AI Agents",
            "Managed LLM tokens: 2,000,000/month",
            "All integrations",
            "API access",
            "Custom AI training",
            "24/7 premium support",
            "Dedicated account manager",
        ]),
        "bot_limit": 10,
        "managed_tokens": 2000000,
        "sort_order": 3,
        "provider_links": [
            {"provider_name": "ilmu_ai", "token_quota": 1000000},
            {"provider_name": "openrouter", "token_quota": 1000000},
        ],
    },
]


async def seed():
    conn = await asyncpg.connect(DB_URL)

    # 1) Seed packages + provider links
    for pkg in PACKAGES:
        provider_links = pkg.pop("provider_links", [])
        exists = await conn.fetchval(
            "SELECT id FROM packages WHERE name = $1", pkg["name"]
        )

        if exists:
            await conn.execute("""UPDATE packages SET
                display_name=$1, price_monthly=$2, price_yearly=$3,
                description=$4, features=$5, bot_limit=$6,
                managed_tokens=$7, sort_order=$8, is_active=TRUE
                WHERE name=$9""",
                pkg["display_name"], pkg["price_monthly"], pkg["price_yearly"],
                pkg["description"], pkg["features"], pkg["bot_limit"],
                pkg["managed_tokens"], pkg["sort_order"], pkg["name"])
            pkg_id = exists
            print(f"  Updated: {pkg['display_name']}")
        else:
            pkg_id = await conn.fetchval("""INSERT INTO packages
                (name, display_name, price_monthly, price_yearly,
                 description, features, bot_limit, managed_tokens,
                 sort_order, is_active)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,TRUE)
                RETURNING id""",
                pkg["name"], pkg["display_name"], pkg["price_monthly"], pkg["price_yearly"],
                pkg["description"], pkg["features"], pkg["bot_limit"],
                pkg["managed_tokens"], pkg["sort_order"])
            print(f"  Created: {pkg['display_name']}")

        # Link providers
        for link in provider_links:
            prov = await conn.fetchrow(
                "SELECT id FROM llm_providers WHERE name = $1", link["provider_name"]
            )
            if prov:
                existing_link = await conn.fetchval(
                    "SELECT id FROM package_providers WHERE package_id=$1 AND provider_id=$2",
                    pkg_id, prov["id"]
                )
                if not existing_link:
                    await conn.execute(
                        "INSERT INTO package_providers (package_id, provider_id, token_quota, is_available) VALUES ($1,$2,$3,TRUE)",
                        pkg_id, prov["id"], link["token_quota"]
                    )
                    print(f"    Linked {link['provider_name']} -> {pkg['display_name']} ({link['token_quota']} tokens)")

    # 2) Create admin user if not exists
    admin = await conn.fetchrow("SELECT id FROM clients WHERE email = $1", "admin@staffbot.my")
    if not admin:
        # Simple password hash (in production use bcrypt from passlib)
        pw = "staffbot@2025"
        # Use passlib if available, otherwise plaintext fallback
        pwd_hash = hashlib.sha256(pw.encode()).hexdigest()
        # Try to use proper hashing
        try:
            from passlib.hash import bcrypt
            pwd_hash = bcrypt.hash(pw)
        except:
            pass

        admin_id = await conn.fetchval("""INSERT INTO clients
            (name, email, password_hash, status, package)
            VALUES ($1,$2,$3,$4,$5) RETURNING id""",
            "Admin", "admin@staffbot.my", pwd_hash, "active", "enterprise")
        print(f"  Created admin user (id={admin_id})")
        print(f"    Email: admin@staffbot.my")
        print(f"    Password: staffbot@2025")
    else:
        print(f"  Admin user already exists (id={admin['id']})")

    await conn.close()
    print("\n  Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
