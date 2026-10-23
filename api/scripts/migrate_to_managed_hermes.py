"""Move existing customers to managed Hermes (docs/RUNBOOK_MANAGED_HERMES.md, Fasa 7).

For each customer:
 1. provision their Hermes container (volume, managed config, limits)
 2. export their old StaffBot memory (client_memory) into a Hermes skill
    `company-knowledge` in their volume (Hermes' own MEMORY.md is only
    ~2,200 chars, so imported knowledge lives in a skill the agent loads
    when relevant)
Once a customer has a hermes_instances row, the channel router sends their
WhatsApp/Telegram messages to Hermes instead of the legacy gateway.

    python -m scripts.migrate_to_managed_hermes --clients 3,7        # dry run
    python -m scripts.migrate_to_managed_hermes --clients 3,7 --apply
    python -m scripts.migrate_to_managed_hermes --all --apply
"""
import argparse
import asyncio
import json
from datetime import datetime

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models.client import Client
from app.models.hermes_instance import HermesInstance
from app.services import hermes_orchestrator as orch

SKILL_DIR = "skills/staffbot-imported/company-knowledge"
MAX_ITEMS = 2000


def build_knowledge_skill(company: str, rows: list) -> dict[str, str]:
    """Return {relative path: content} for the imported knowledge skill."""
    groups: dict[str, list[str]] = {}
    for content, metadata, created_at in rows:
        meta = metadata if isinstance(metadata, dict) else json.loads(metadata or "{}")
        kind = meta.get("memory_type") or meta.get("type") or "note"
        stamp = created_at.strftime("%Y-%m-%d") if isinstance(created_at, datetime) else ""
        groups.setdefault(kind, []).append(f"- ({stamp}) {content.strip()}")
    body = [f"# Pengetahuan syarikat: {company}", "",
            "Diimport dari StaffBot lama. Fakta, keutamaan dan maklumat syarikat yang pernah disimpan.", ""]
    for kind in sorted(groups):
        body += [f"## {kind}", *groups[kind], ""]
    skill = "\n".join([
        "---",
        "name: company-knowledge",
        f"description: Facts, preferences and business knowledge about {company} imported from the old StaffBot memory. Use when answering questions about the company, its products, prices, customers or how the owner likes things done.",
        "---",
        "",
        f"# Company knowledge — {company}",
        "",
        f"{sum(len(v) for v in groups.values())} items imported. Read `references/knowledge.md` for the full list.",
        "If something here conflicts with what the user tells you now, trust the user and update your memory.",
        "",
    ])
    return {f"{SKILL_DIR}/SKILL.md": skill, f"{SKILL_DIR}/references/knowledge.md": "\n".join(body)}


async def migrate(client_ids: list[int], apply: bool) -> None:
    async with async_session_factory() as db:
        for cid in client_ids:
            client = (await db.execute(select(Client).where(Client.id == cid))).scalar_one_or_none()
            if not client:
                print(f"#{cid}: not found, skipped")
                continue
            exists = (await db.execute(select(HermesInstance).where(HermesInstance.client_id == cid))).scalar_one_or_none()
            rows = (await db.execute(text(
                "SELECT content, metadata, created_at FROM client_memory WHERE client_id = :cid "
                "ORDER BY created_at DESC LIMIT :lim"), {"cid": cid, "lim": MAX_ITEMS})).all()
            print(f"#{cid} {client.company or client.name}: package={client.package} "
                  f"hermes={'yes' if exists else 'no'} memories={len(rows)}")
            if not apply:
                continue
            try:
                await orch.provision(db, cid)
                if rows:
                    files = build_knowledge_skill(client.company or client.name, rows)
                    await asyncio.to_thread(orch.write_files_to_volume, cid, files)
                print(f"#{cid}: migrated")
            except Exception as e:
                print(f"#{cid}: FAILED {e}")
    if not apply:
        print("dry run: nothing changed (use --apply)")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", help="comma-separated client ids")
    ap.add_argument("--all", action="store_true", help="all active clients without a Hermes instance")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.all:
        async with async_session_factory() as db:
            ids = [i for (i,) in (await db.execute(
                select(Client.id).where(Client.status == "active",
                                        ~Client.id.in_(select(HermesInstance.client_id))).order_by(Client.id)
            )).all()]
    elif args.clients:
        ids = [int(x) for x in args.clients.split(",") if x.strip()]
    else:
        ap.error("use --clients or --all")
    await migrate(ids, args.apply)


if __name__ == "__main__":
    asyncio.run(main())
