#!/usr/bin/env python3
"""Seed packages into StaffBot.my database."""
import asyncio, asyncpg, json, sys

DB_URL = "postgresql://marz:staffbot123@127.0.0.1:5432/staffbot_db"

PACKAGES = [
    ("trial", "Trial Percuma", 0, None, "Cuba StaffBot.my percuma 7 hari. Tak perlu kad kredit.",
     ["Chat dengan AI Staff", "Memory berterusan", "1 bot AI", "1,000 token percuma",
      "Akses dashboard", "Support WhatsApp", "Managed: OpenRouter"], 1, 1000, 0),
    ("basic", "Basic", 49, 499, "Sesuai untuk SME yang nak automasi asas.",
     ["Chat dengan AI Staff", "Memory berterusan", "1 bot AI", "10,000 token/bulan",
      "Task scheduling", "Akses dashboard", "Support WhatsApp", "Integrasi Telegram",
      "Managed: OpenRouter"], 1, 10000, 1),
    ("pro", "Pro", 149, 1499, "Untuk bisnes yang perlukan automasi penuh.",
     ["Semua Basic +", "3 bot AI", "50,000 token/bulan", "GDrive integration",
      "Email integration", "API integration", "Token terurus", "Priority support",
      "Managed: OpenRouter + Ilmu AI"], 3, 50000, 2),
    ("enterprise", "Enterprise", 499, 4999, "Untuk syarikat yang perlukan skala penuh.",
     ["Semua Pro +", "10 bot AI", "500,000 token/bulan", "Token premium",
      "Dedicated support", "Custom integration", "SLA guarantee", "Early access",
      "Managed: OpenRouter + Ilmu AI + Premium"], 10, 500000, 3),
]


async def seed():
    conn = await asyncpg.connect(DB_URL)

    for name, display, monthly, yearly, desc, features, bots, tokens, sort_idx in PACKAGES:
        features_json = json.dumps(features)

        exists = await conn.fetchval(
            "SELECT id FROM packages WHERE name = $1", name
        )

        if exists:
            await conn.execute(
                "UPDATE packages SET display_name=$1, price_monthly=$2, price_yearly=$3, "
                "description=$4, features=$5, bot_limit=$6, managed_tokens=$7, "
                "sort_order=$8, is_active=TRUE WHERE name=$9",
                display, monthly, yearly, desc, features_json, bots, tokens, sort_idx, name
            )
            print(f"  Updated: {display}")
        else:
            await conn.execute(
                "INSERT INTO packages (name, display_name, price_monthly, price_yearly, "
                "description, features, bot_limit, managed_tokens, sort_order, is_active) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,TRUE)",
                name, display, monthly, yearly, desc, features_json, bots, tokens, sort_idx
            )
            print(f"  Created: {display}")

    await conn.close()
    print("\n  Packages seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
