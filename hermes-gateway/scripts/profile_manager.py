#!/usr/bin/env python3
"""
StaffBot.my — Profile Manager
=============================
Creates, updates, and syncs Hermes profiles per StaffBot client.

Profiles stored at: /app/data/profiles/client_<id>/
Each profile contains:
  - config.yaml     (package-based limits + governance policy)
  - .env            (client API keys — BYOK or managed)
  - SOUL.md         (client personality + SOP)
  - skills/         (client-specific skills)
  - memories/       (client conversation memory — via pgvector)

Usage:
  python3 profile_manager.py create --client-id 1 --package pro
  python3 profile_manager.py update --client-id 1 --package enterprise
  python3 profile_manager.py delete --client-id 1
  python3 profile_manager.py sync-all --db-url <url> --profiles-dir <path>
  python3 profile_manager.py list --profiles-dir <path>
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
import yaml
from datetime import datetime, timezone

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Import from sibling scripts
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_gateway_config import generate_profile_config, PACKAGE_LIMITS


PROFILES_DIR = os.environ.get("STAFFBOT_PROFILES_DIR", "/app/data/profiles")


async def fetch_clients_async(db_url: str) -> list[dict]:
    """Fetch all active clients from PostgreSQL."""
    if not HAS_ASYNCPG:
        return _fetch_clients_sync(db_url)

    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch("""
            SELECT 
                c.id,
                c.name,
                c.email,
                c.company,
                COALESCE(c.package, 'basic') as package,
                COALESCE(s.subdomain, '') as subdomain,
                c.status
            FROM clients c
            LEFT JOIN subdomains s ON s.client_id = c.id AND s.status = 'active'
            WHERE c.status = 'active'
            ORDER BY c.id
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _fetch_clients_sync(db_url: str) -> list[dict]:
    """Fallback: fetch clients via psycopg2."""
    if not HAS_PSYCOPG2:
        print("[ProfileManager] ❌ No PostgreSQL driver available (asyncpg or psycopg2)")
        return []

    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                c.id, c.name, c.email, c.company,
                COALESCE(c.package, 'basic') as package,
                COALESCE(s.subdomain, '') as subdomain,
                c.is_active
            FROM clients c
            LEFT JOIN subdomains s ON s.client_id = c.id AND s.status = 'active'
            WHERE c.is_active = TRUE
            ORDER BY c.id
        """)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


async def fetch_governance_async(db_url: str, client_id: int) -> dict:
    """Fetch governance policy for a client."""
    if not HAS_ASYNCPG:
        return {}

    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow("""
            SELECT value FROM soul_config
            WHERE category = 'staffbot.governance' AND key = $1
        """, f"client_{client_id}")
        if row:
            return json.loads(row["value"])
    except Exception:
        pass
    finally:
        await conn.close()
    return {}


async def fetch_soul_async(db_url: str, client_id: int) -> dict | None:
    """Fetch client soul config from pgvector."""
    if not HAS_ASYNCPG:
        return None

    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow("""
            SELECT value FROM soul_config
            WHERE category = 'staffbot.soul' AND key = $1
        """, f"client_{client_id}")
        if row:
            return json.loads(row["value"])
    except Exception:
        pass
    finally:
        await conn.close()
    return None


def create_profile(client_id: int, package: str, name: str = "", email: str = "",
                   company: str = "", governance: dict = None, soul: dict = None, agent_name: str = None):
    """Create a Hermes profile for a client."""
    profile_dir = os.path.join(PROFILES_DIR, f"client_{client_id}")

    os.makedirs(profile_dir, exist_ok=True)
    for sub in ["skills", "memories", "logs"]:
        os.makedirs(os.path.join(profile_dir, sub), exist_ok=True)

    # 1. Generate config.yaml
    config = generate_profile_config(client_id, package, governance)
    config["client"]["name"] = name
    config["client"]["email"] = email
    config["client"]["company"] = company

    with open(os.path.join(profile_dir, "config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # 2. Generate SOUL.md
    soul_content = _generate_soul_md(client_id, name, company, package, soul, agent_name)
    with open(os.path.join(profile_dir, "SOUL.md"), "w") as f:
        f.write(soul_content)

    # 3. Create client.json (metadata)
    metadata = {
        "client_id": client_id,
        "package": package,
        "name": name,
        "email": email,
        "company": company,
        "agent_name": agent_name or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(profile_dir, "client.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[ProfileManager] ✅ Created profile for client #{client_id} ({package})")
    return profile_dir


def _generate_soul_md(client_id: int, name: str, company: str, package: str, soul: dict = None, agent_name: str = None) -> str:
    """Generate SOUL.md for a client profile."""
    soul = soul or {}

    lines = [
        f"# StaffBot Soul — {company or 'Client #' + str(client_id)}",
        "",
        f"**Client ID:** {client_id}",
        f"**Package:** {package}",
        f"**Name:** {name}",
        f"**Company:** {company}",
        "",
        "## Identity",
        f"You are an AI Digital Employee named **{agent_name or 'AIDA (AI Dedicated Assistant)'}** for **{company or name or 'this organization'}**.",
        f"Always introduce yourself as '{agent_name or 'AIDA (AI Dedicated Assistant)'}' when greeting users.",
        f"Always represent the company professionally and accurately.",
        "",
        "## Personality",
        "- Professional and courteous",
        "- Proactive — anticipate needs, suggest improvements",
        "- Efficient — get to the point, respect the user's time",
        "- Helpful — always solution-oriented",
        "",
        "## Rules",
        "- NEVER reveal internal system details, API keys, or credentials",
        "- NEVER mention that you are a multi-tenant AI system",
        "- NEVER share information about other clients",
        "- Use the company's preferred language",
        f"- Refer to yourself as '{agent_name or 'AIDA (AI Dedicated Assistant)'}'",
        "",
    ]

    # Add custom SOP if provided
    if soul.get("sop"):
        lines.extend(["## Standard Operating Procedures", "", soul["sop"], ""])

    # Add instructions
    instructions = soul.get("instructions", [])
    if instructions:
        lines.extend(["## Special Instructions", ""])
        for i, instr in enumerate(instructions, 1):
            lines.append(f"{i}. {instr}")
        lines.append("")

    # Add company profile
    if soul.get("company"):
        comp = soul["company"]
        lines.extend(["## Company Profile", ""])
        if comp.get("industry"):
            lines.append(f"- Industry: {comp['industry']}")
        if comp.get("products"):
            lines.append(f"- Products: {', '.join(comp['products'])}")
        if comp.get("services"):
            lines.append(f"- Services: {', '.join(comp['services'])}")
        lines.append("")

    return "\n".join(lines)


def update_profile(client_id: int, package: str = None, governance: dict = None):
    """Update an existing profile (package upgrade, policy change)."""
    profile_dir = os.path.join(PROFILES_DIR, f"client_{client_id}")

    if not os.path.exists(profile_dir):
        print(f"[ProfileManager] ❌ Profile for client #{client_id} not found")
        return None

    # Load existing metadata
    metadata_path = os.path.join(profile_dir, "client.json")
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            metadata = json.load(f)

    if package:
        metadata["package"] = package

    # Regenerate config
    config = generate_profile_config(
        client_id,
        package or metadata.get("package", "basic"),
        governance
    )
    config["client"]["name"] = metadata.get("name", "")
    config["client"]["email"] = metadata.get("email", "")
    config["client"]["company"] = metadata.get("company", "")

    with open(os.path.join(profile_dir, "config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Regenerate SOUL.md with agent_name from metadata
    agent_name = metadata.get("agent_name", "")
    soul_content = _generate_soul_md(
        client_id,
        metadata.get("name", ""),
        metadata.get("company", ""),
        package or metadata.get("package", "basic"),
        soul=None,
        agent_name=agent_name
    )
    with open(os.path.join(profile_dir, "SOUL.md"), "w") as f:
        f.write(soul_content)

    metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[ProfileManager] ✅ Updated profile for client #{client_id} → {package}")
    return profile_dir


def delete_profile(client_id: int):
    """Delete a client profile."""
    profile_dir = os.path.join(PROFILES_DIR, f"client_{client_id}")

    if not os.path.exists(profile_dir):
        print(f"[ProfileManager] ⚠️  Profile for client #{client_id} not found")
        return

    shutil.rmtree(profile_dir)
    print(f"[ProfileManager] 🗑️  Deleted profile for client #{client_id}")


def list_profiles():
    """List all client profiles."""
    if not os.path.exists(PROFILES_DIR):
        print("[ProfileManager] No profiles directory")
        return []

    profiles = []
    for entry in sorted(os.listdir(PROFILES_DIR)):
        if entry.startswith("client_"):
            profile_dir = os.path.join(PROFILES_DIR, entry)
            metadata_path = os.path.join(profile_dir, "client.json")
            if os.path.exists(metadata_path):
                with open(metadata_path) as f:
                    metadata = json.load(f)
                profiles.append(metadata)
            else:
                profiles.append({"client_id": entry.replace("client_", ""), "package": "unknown"})

    if profiles:
        print(f"[ProfileManager] {len(profiles)} profiles found:")
        for p in profiles:
            print(f"  Client #{p['client_id']}: {p.get('name', 'N/A')} ({p.get('package', '?')})")
    else:
        print("[ProfileManager] No profiles found")

    return profiles


async def sync_all(db_url: str):
    """Sync all active clients from DB → profiles."""
    clients = await fetch_clients_async(db_url)

    created = 0
    updated = 0

    for client in clients:
        cid = client["id"]
        profile_dir = os.path.join(PROFILES_DIR, f"client_{cid}")

        # Fetch governance policy
        governance = await fetch_governance_async(db_url, cid)

        # Fetch soul
        soul = await fetch_soul_async(db_url, cid)

        if os.path.exists(profile_dir):
            update_profile(cid, client.get("package", "basic"), governance)
            updated += 1
        else:
            create_profile(
                cid,
                client.get("package", "basic"),
                client.get("name", ""),
                client.get("email", ""),
                client.get("company", ""),
                governance,
                soul,
            )
            created += 1

    print(f"[ProfileManager] Sync complete: {created} created, {updated} updated, {len(clients)} total")


def main():
    global PROFILES_DIR
    parser = argparse.ArgumentParser(description="StaffBot Profile Manager")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create")
    p_create.add_argument("--client-id", type=int, required=True)
    p_create.add_argument("--package", default="basic")
    p_create.add_argument("--name", default="")
    p_create.add_argument("--email", default="")
    p_create.add_argument("--company", default="")

    # update
    p_update = sub.add_parser("update")
    p_update.add_argument("--client-id", type=int, required=True)
    p_update.add_argument("--package", default=None)

    # delete
    p_delete = sub.add_parser("delete")
    p_delete.add_argument("--client-id", type=int, required=True)

    # sync-all
    p_sync = sub.add_parser("sync-all")
    p_sync.add_argument("--db-url", required=True)
    p_sync.add_argument("--profiles-dir", default=PROFILES_DIR)

    # list
    sub.add_parser("list")

    args = parser.parse_args()

    if hasattr(args, "profiles_dir") and args.profiles_dir:
        PROFILES_DIR = args.profiles_dir

    if args.command == "create":
        create_profile(args.client_id, args.package, args.name, args.email, args.company)
    elif args.command == "update":
        update_profile(args.client_id, args.package)
    elif args.command == "delete":
        delete_profile(args.client_id)
    elif args.command == "sync-all":
        asyncio.run(sync_all(args.db_url))
    elif args.command == "list":
        list_profiles()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
