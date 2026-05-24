#!/usr/bin/env python3
"""Seed default LLM providers into StaffBot.my database."""
import asyncio, asyncpg, json, sys

DB_URL = "postgresql://staffbot:staffbot123@db:5432/staffbot_db"

PROVIDERS = [
    {
        "name": "ilmu_ai",
        "display_name": "Ilmu AI",
        "base_url": "https://api.ilmu.ai/v1",
        "models": json.dumps(["ilmu-nemo-nano"]),
        "default_model": "ilmu-nemo-nano",
        "description": "Model AI tempatan Malaysia — dioptimumkan untuk Bahasa Malaysia dan dialek tempatan. Lebih tepat untuk konteks perniagaan tempatan.",
        "api_key_encrypted": "REPLACE_WITH_YOUR_KEY",
        "sort_order": 0,
    },
    {
        "name": "openrouter",
        "display_name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": json.dumps([
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4",
            "anthropic/claude-3.5-haiku",
            "google/gemini-2.0-flash",
            "deepseek/deepseek-chat",
        ]),
        "default_model": "openai/gpt-4o-mini",
        "description": "Akses pelbagai model AI dari pelbagai provider terkemuka.",
        "sort_order": 1,
    },
]


async def seed():
    conn = await asyncpg.connect(DB_URL)
    for prov in PROVIDERS:
        exists = await conn.fetchval(
            "SELECT id FROM llm_providers WHERE name = $1", prov["name"]
        )
        if exists:
            await conn.execute(
                """UPDATE llm_providers SET
                    display_name=$1, base_url=$2, models=$3,
                    default_model=$4, description=$5, sort_order=$6,
                    api_key_encrypted=$7, is_active=TRUE
                WHERE name=$8""",
                prov["display_name"], prov["base_url"], prov["models"],
                prov["default_model"], prov["description"], prov["sort_order"],
                prov.get("api_key_encrypted", ""), prov["name"]
            )
            print(f"  Updated: {prov['display_name']}")
        else:
            await conn.execute(
                """INSERT INTO llm_providers
                    (name, display_name, base_url, models, default_model,
                     description, api_key_encrypted, sort_order, is_active)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,TRUE)""",
                prov["name"], prov["display_name"], prov["base_url"], prov["models"],
                prov["default_model"], prov["description"],
                prov.get("api_key_encrypted", ""), prov["sort_order"]
            )
            print(f"  Created: {prov['display_name']}")
    await conn.close()
    print("\n  LLM providers seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
