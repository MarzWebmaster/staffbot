#!/usr/bin/env python3
"""Seed default LLM providers into StaffBot.my database.

Creates the base managed providers: OpenRouter and Ilmu AI.
Run after seed_packages.py or whenever a fresh DB needs provider defaults.
"""
import asyncio, asyncpg, json, sys

DB_URL = "postgresql://marz:staffbot123@127.0.0.1:5432/staffbot_db"

PROVIDERS = [
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
            "meta-llama/llama-3.3-70b-instruct",
            "mistralai/mistral-large",
        ]),
        "default_model": "openai/gpt-4o-mini",
        "description": "Akses pelbagai model AI dari pelbagai provider terkemuka melalui satu API. Termasuk OpenAI, Anthropic, Google, Meta, dan banyak lagi.",
        "sort_order": 0,
    },
    {
        "name": "ilmui",
        "display_name": "Ilmu AI",
        "base_url": "https://api.ilmugpt.ai/v1",
        "models": json.dumps([
            "ilmu-ai/ilmu-ai-v1",
            "ilmu-ai/ilmu-ai-v2",
            "ilmu-ai/ilmu-chat",
        ]),
        "default_model": "ilmu-ai/ilmu-chat",
        "description": "Model AI tempatan Malaysia — dioptimumkan untuk Bahasa Malaysia dan dialek tempatan. Lebih tepat untuk konteks perniagaan tempatan.",
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
                    is_active=TRUE
                WHERE name=$7""",
                prov["display_name"], prov["base_url"], prov["models"],
                prov["default_model"], prov["description"], prov["sort_order"],
                prov["name"]
            )
            print(f"  Updated: {prov['display_name']}")
        else:
            await conn.execute(
                """INSERT INTO llm_providers
                    (name, display_name, base_url, models, default_model,
                     description, sort_order, is_active)
                VALUES ($1,$2,$3,$4,$5,$6,$7,TRUE)""",
                prov["name"], prov["display_name"], prov["base_url"], prov["models"],
                prov["default_model"], prov["description"], prov["sort_order"]
            )
            print(f"  Created: {prov['display_name']}")

    await conn.close()
    print("\n  LLM providers seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
