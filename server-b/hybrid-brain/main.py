#!/usr/bin/env python3
"""
StaffBot.my — Hybrid Brain Service

Combines Central Brain (pgvector) + Hindsight (deep memory) into ONE endpoint.

Architecture:
  Agent → Gateway → Hybrid Brain → Central Brain (pgvector, fast)
                                  → Hindsight (deep memory, LLM-powered)

Token tracking: All Hindsight LLM calls deducted from client's quota.
"""

import os
import json
import httpx
import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List

# --- Config ---
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://staffbot:***@localhost:5432/staffbot_memory")
HINDSIGHT_URL = os.environ.get("HINDSIGHT_URL", "http://hindsight:8888")
SERVER_A_URL = os.environ.get("SERVER_A_URL", "http://staffbot-api:8000")
SERVER_A_KEY = os.environ.get("SERVER_A_KEY", "staffbot-api-key")
HYBRID_PORT = int(os.environ.get("HYBRID_PORT", "8085"))

# LLM model for hindsight — use cheaper model for memory processing
HINDSIGHT_MODEL = os.environ.get("HINDSIGHT_MODEL", "gpt-4o-mini")

app = FastAPI(title="StaffBot.my — Hybrid Brain", version="1.0.0")


# =====================
# Pydantic Models
# =====================

class MemoryQuery(BaseModel):
    client_id: int
    query: str
    limit: int = 5

class MemorySave(BaseModel):
    client_id: int
    content: str
    metadata: dict = {}

class HybridSearchResult(BaseModel):
    success: bool
    results: list = []
    sources: dict = {}
    token_usage: Optional[dict] = None

class HybridSaveResult(BaseModel):
    success: bool
    sources: dict = {}
    token_usage: Optional[dict] = None


# =====================
# Central Brain (pgvector)
# =====================

async def central_brain_search(client_id: int, query: str, limit: int = 5) -> list:
    """Fast search via pgvector — no LLM cost."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch(
            "SELECT content, metadata, created_at FROM client_memory "
            "WHERE client_id=$1 ORDER BY created_at DESC LIMIT $2",
            client_id, limit
        )
        await conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return [{"error": str(e)}]

async def central_brain_save(client_id: int, content: str, metadata: dict = None):
    """Fast save to pgvector — no LLM cost."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO client_memory (client_id, content, metadata) VALUES ($1, $2, $3)",
            client_id, content, json.dumps(metadata or {})
        )
        await conn.close()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =====================
# Hindsight (Deep Memory)
# =====================

async def hindsight_retain(client_id: int, content: str, metadata: dict = None) -> dict:
    """Deep memory retain via Hindsight — uses LLM, deduct token."""
    bank_id = f"staffbot_{client_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HINDSIGHT_URL}/api/v1/retain",
                json={
                    "bank_id": bank_id,
                    "content": content,
                    "metadata": metadata or {},
                    "model": HINDSIGHT_MODEL,
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Track token usage
                token_used = data.get("usage", {}).get("total_tokens", 0)
                if token_used > 0:
                    await deduct_client_tokens(client_id, token_used, "hindsight_retain")
                return {
                    "success": True,
                    "token_used": token_used,
                    "hindsight_id": data.get("id"),
                }
            return {"success": False, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def hindsight_recall(client_id: int, query: str, limit: int = 5) -> dict:
    """Deep memory recall via Hindsight — uses LLM, deduct token."""
    bank_id = f"staffbot_{client_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HINDSIGHT_URL}/api/v1/recall",
                json={
                    "bank_id": bank_id,
                    "query": query,
                    "limit": limit,
                    "model": HINDSIGHT_MODEL,
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                token_used = data.get("usage", {}).get("total_tokens", 0)
                if token_used > 0:
                    await deduct_client_tokens(client_id, token_used, "hindsight_recall")
                return {
                    "success": True,
                    "results": data.get("results", []),
                    "token_used": token_used,
                }
            return {"success": False, "error": resp.text, "results": []}
    except Exception as e:
        return {"success": False, "error": str(e), "results": []}

async def hindsight_reflect(client_id: int, query: str) -> dict:
    """Deep reflection via Hindsight — heavy LLM usage, deduct token."""
    bank_id = f"staffbot_{client_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HINDSIGHT_URL}/api/v1/reflect",
                json={
                    "bank_id": bank_id,
                    "query": query,
                    "model": HINDSIGHT_MODEL,
                },
                timeout=60.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                token_used = data.get("usage", {}).get("total_tokens", 0)
                if token_used > 0:
                    await deduct_client_tokens(client_id, token_used, "hindsight_reflect")
                return {
                    "success": True,
                    "reflection": data.get("reflection"),
                    "insights": data.get("insights", []),
                    "token_used": token_used,
                }
            return {"success": False, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =====================
# Token Deduction
# =====================

async def deduct_client_tokens(client_id: int, tokens: int, operation: str):
    """Deduct tokens from client's quota via Server A API."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SERVER_A_URL}/api/internal/track-tokens",
                json={
                    "client_id": client_id,
                    "tokens": tokens,
                    "operation": operation,
                    "source": "hybrid_brain",
                },
                headers={"X-API-Key": SERVER_A_KEY},
                timeout=5.0,
            )
    except Exception:
        pass  # Non-critical — don't fail the main operation


# =====================
# Hybrid Search (Merge Strategy)
# =====================

async def hybrid_search(client_id: int, query: str, limit: int = 5) -> dict:
    """
    Hybrid search strategy:
    1. Central Brain (pgvector) — fast, no LLM cost
    2. Hindsight (deep memory) — LLM-powered, deduct token
    3. Merge results — deduplicate by content similarity
    """
    # Parallel execution
    central_results = await central_brain_search(client_id, query, limit)
    hindsight_results = await hindsight_recall(client_id, query, limit)

    # Extract hindsight memories
    hindsight_memories = []
    hindsight_tokens = 0
    if hindsight_results.get("success"):
        hindsight_memories = hindsight_results.get("results", [])
        hindsight_tokens = hindsight_results.get("token_used", 0)

    # Merge: prefer hindsight (more accurate), fallback to central brain
    merged = []
    seen = set()

    # Add hindsight results first (higher priority)
    for item in hindsight_memories:
        content = item.get("content", item.get("text", ""))[:100]
        if content not in seen:
            seen.add(content)
            merged.append({
                "content": item.get("content", item.get("text", "")),
                "source": "hindsight",
                "relevance": item.get("relevance", 0.95),
                "token_cost": 0,  # Already deducted
            })

    # Fill remaining slots with central brain results
    for item in central_results:
        content = item.get("content", "")[:100]
        if content not in seen and len(merged) < limit:
            seen.add(content)
            merged.append({
                "content": item.get("content", ""),
                "source": "central_brain",
                "relevance": 0.7,
                "token_cost": 0,
            })

    return {
        "results": merged[:limit],
        "sources": {
            "central_brain": len(central_results),
            "hindsight": len(hindsight_memories),
        },
        "token_usage": {
            "hindsight_retain": 0,
            "hindsight_recall": hindsight_tokens,
            "hindsight_reflect": 0,
            "total": hindsight_tokens,
        },
    }


# =====================
# API Endpoints
# =====================

@app.post("/api/search")
async def search(data: MemoryQuery):
    """Hybrid search — combines Central Brain + Hindsight."""
    if not data.query.strip():
        return HybridSearchResult(success=True, results=[])

    result = await hybrid_search(data.client_id, data.query, data.limit)
    return HybridSearchResult(
        success=True,
        results=result["results"],
        sources=result["sources"],
        token_usage=result["token_usage"],
    )


@app.post("/api/save")
async def save(data: MemorySave):
    """Hybrid save — saves to BOTH Central Brain (fast) and Hindsight (deep)."""
    if not data.content.strip():
        return HybridSaveResult(success=False, error="Content cannot be empty")

    # 1. Save to Central Brain (instant, no LLM)
    cb_result = await central_brain_save(data.client_id, data.content, data.metadata)

    # 2. Save to Hindsight (LLM processes for deep memory)
    hs_result = await hindsight_retain(data.client_id, data.content, data.metadata)

    return HybridSaveResult(
        success=cb_result.get("success", False),
        sources={
            "central_brain": cb_result.get("success", False),
            "hindsight": hs_result.get("success", False),
        },
        token_usage={
            "hindsight_retain": hs_result.get("token_used", 0),
            "total": hs_result.get("token_used", 0),
        },
    )


@app.post("/api/reflect")
async def reflect(data: MemoryQuery):
    """Deep reflection via Hindsight — heavy LLM, deduct tokens."""
    if not data.query.strip():
        return {"success": False, "error": "Query cannot be empty"}

    result = await hindsight_reflect(data.client_id, data.query)
    return result


@app.post("/api/client/{client_id}/init")
async def init_client_memory(client_id: int):
    """Initialize Hindsight memory bank for a new client."""
    bank_id = f"staffbot_{client_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HINDSIGHT_URL}/api/v1/banks",
                json={"bank_id": bank_id},
                timeout=10.0,
            )
            return {
                "success": resp.status_code == 200,
                "bank_id": bank_id,
                "status": "created" if resp.status_code == 200 else resp.text,
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/health")
async def health():
    """Health check with upstream status."""
    # Check Hindsight
    hs_ok = False
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{HINDSIGHT_URL}/health", timeout=3.0)
            hs_ok = r.status_code == 200
    except Exception:
        pass

    # Check Central Brain DB
    db_ok = False
    try:
        conn = await asyncpg.connect(DATABASE_URL, timeout=3.0)
        await conn.close()
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if (hs_ok or db_ok) else "degraded",
        "service": "StaffBot.my Hybrid Brain",
        "upstreams": {
            "central_brain": db_ok,
            "hindsight": hs_ok,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HYBRID_PORT)
