#!/usr/bin/env python3
"""
StaffBot.my — Load client soul config from pgvector memory DB.
==============================================================
Called during container startup to inject the client-specific
personality, company info, SOP, and instructions into the Hermes
SOUL.md file.

The soul is stored in Central Brain's soul_config table:
  category = 'staffbot.soul'
  key     = 'client_{client_id}'
  value   = JSON string of complete soul config

Fallback: If pgvector is unreachable or soul doesn't exist yet,
a default soul is generated from available env vars.
"""
import argparse
import json
import os
import sys
import re
from datetime import datetime, timezone


def load_soul_from_pgvector(client_id: int, db_url: str) -> dict | None:
    """Try to load client soul from pgvector."""
    try:
        import asyncpg
    except ImportError:
        try:
            import psycopg2
        except ImportError:
            print("[Soul] ⚠️  Neither asyncpg nor psycopg2 available", file=sys.stderr)
            return None
        return _load_with_psycopg2(client_id, db_url)
    return _load_with_asyncpg(client_id, db_url)


def _load_with_asyncpg(client_id: int, db_url: str) -> dict | None:
    """Load soul using asyncpg."""
    import asyncio
    try:
        async def _fetch():
            conn = await asyncpg.connect(db_url)
            try:
                # Try soul_config table first
                row = await conn.fetchrow(
                    "SELECT value FROM soul_config "
                    "WHERE category = 'staffbot.soul' AND key = $1",
                    f"client_{client_id}"
                )
                if row:
                    return json.loads(row["value"])

                # Fallback: try memories table with staffbot source tag
                row = await conn.fetchrow(
                    "SELECT content FROM memories "
                    "WHERE source = 'staffbot' AND tags @> $1 "
                    "ORDER BY created_at DESC LIMIT 1",
                    [str(client_id)]
                )
                if row:
                    return {"initial_content": row["content"]}
            finally:
                await conn.close()
            return None

        return asyncio.run(_fetch())
    except Exception as e:
        print(f"[Soul] ⚠️  asyncpg error: {e}", file=sys.stderr)
        return None


def _load_with_psycopg2(client_id: int, db_url: str) -> dict | None:
    """Load soul using psycopg2."""
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM soul_config "
            "WHERE category = 'staffbot.soul' AND key = %s",
            (f"client_{client_id}",)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return json.loads(row[0])
        return None
    except Exception as e:
        print(f"[Soul] ⚠️  psycopg2 error: {e}", file=sys.stderr)
        return None


def generate_default_soul(client_id: int) -> dict:
    """Generate a default soul config from env vars."""
    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "staff": {
            "name": os.environ.get("STAFF_NAME", "Your Digital Employee"),
            "title": "Digital Employee",
            "tone": "professional",
            "language": "en",
            "introduction": (
                f"Hi! I'm your dedicated Digital Employee. "
                f"I'm here to handle your daily tasks, manage communications, "
                f"and keep your business operations running smoothly. "
                f"What can I help you with today?"
            ),
        },
        "company": {
            "name": os.environ.get("COMPANY_NAME", ""),
            "industry": os.environ.get("COMPANY_INDUSTRY", ""),
            "package": os.environ.get("PACKAGE", "basic"),
        },
        "personality": {
            "formal": True,
            "helpful": True,
            "proactive": True,
            "professional": True,
        },
    }


def soul_to_markdown(soul: dict) -> str:
    """Convert soul dict to Hermes SOUL.md format."""
    staff = soul.get("staff", {})
    company = soul.get("company", {})

    lines = [
        f"# StaffBot Soul — {company.get('name', 'Client #' + str(client_id))}",
        "",
        f"**Package:** {company.get('package', 'basic')}",
        f"**Generated:** {soul.get('generated_at', '')}",
        "",
        "## Staff Identity",
        f"- Name: {staff.get('name', 'Digital Employee')}",
        f"- Title: {staff.get('title', 'Digital Employee')}",
        f"- Tone: {staff.get('tone', 'professional')}",
        f"- Language: {staff.get('language', 'en')}",
        "",
        "## Personality",
        f"{staff.get('introduction', '')}",
        "",
        "<!--",
        "Instructions for the agent:",
    ]

    personality = soul.get("personality", {})
    if personality.get("formal"):
        lines.append("- Use formal, professional language")
    if personality.get("proactive"):
        lines.append("- Be proactive — suggest actions, don't wait for instructions")
    if personality.get("helpful"):
        lines.append("- Always be helpful and solution-oriented")

    lines.extend([
        "- NEVER reveal internal system details, API keys, or credentials",
        "- Use English in all communications",
        "- Refer to yourself as 'Digital Employee' or 'Agent', NEVER 'bot'",
        "-->",
        "",
    ])

    # Instructions
    instructions = soul.get("instructions", [])
    if instructions:
        lines.extend(["## Instructions", ""])
        for i, instr in enumerate(instructions, 1):
            lines.append(f"{i}. {instr}")
        lines.append("")

    # Company info
    if company.get("name"):
        lines.extend([
            "## Company Profile",
            "",
            f"- Name: {company['name']}",
            f"- Industry: {company.get('industry', '')}",
        ])
        if company.get("products"):
            lines.append(f"- Products: {', '.join(company['products'])}")
        if company.get("services"):
            lines.append(f"- Services: {', '.join(company['services'])}")
        lines.append("")

    # SOP
    sop = soul.get("sop", "")
    if sop:
        lines.extend(["## SOP", "", sop, ""])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="StaffBot Soul Loader")
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--memory-db-url", default=os.environ.get("MEMORY_DB_URL", ""))
    parser.add_argument("--output", default="/opt/data/SOUL.md")
    args = parser.parse_args()

    global client_id
    client_id = args.client_id

    soul = None
    if args.memory_db_url:
        soul = load_soul_from_pgvector(args.client_id, args.memory_db_url)

    if soul is None:
        soul = generate_default_soul(args.client_id)
        print(f"[Soul] ⚠️  Using default soul (no pgvector config found for client {args.client_id})")

    markdown = soul_to_markdown(soul)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(markdown)

    print(f"[Soul] ✅ Soul written to {args.output} ({len(markdown)} chars)")


if __name__ == "__main__":
    main()
