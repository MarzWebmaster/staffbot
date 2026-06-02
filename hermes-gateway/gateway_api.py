#!/usr/bin/env python3
"""
StaffBot.my — Hermes Gateway API v2.1
=====================================
Direct LLM calls via httpx — no subprocess overhead.
Provider config via env vars (MIMO_API_KEY, MIMO_BASE_URL).
"""

import asyncio, json, os, sys, time, yaml
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/opt/staffbot/scripts")
from rate_limiter import RateLimiter
from request_queue import RequestQueue
from security import SecurityMiddleware

GATEWAY_AUTH = os.environ.get("GATEWAY_AUTH_TOKEN", "gw-staffbot-secure-key-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
PROFILES_DIR = os.environ.get("STAFFBOT_PROFILES_DIR", "/app/data/profiles")

# Provider configs — keys from env vars
MIMO_KEY = os.environ.get("MIMO_API_KEY", "")
MIMO_BASE = os.environ.get("MIMO_BASE_URL", "https://jemaahapi.tail5cfbb9.ts.net/v1")

PROVIDERS = {
    "mimo": {
        "base_url": MIMO_BASE,
        "api_key": MIMO_KEY,
        "models": ["mimo/mimo-v2.5-pro", "mimo/mimo-v2.5", "mimo/mimo-v2-omni", "mimo/mimo-v2-flash"],
        "default_model": "mimo/mimo-v2.5",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
    },
}

app = FastAPI(title="StaffBot.my Gateway v2.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

rate_limiter = RateLimiter()
request_queue = RequestQueue()
security = SecurityMiddleware(db_url=DATABASE_URL)


class ChatRequest(BaseModel):
    client_id: int
    content: str
    provider: str = "mimo"
    model: Optional[str] = None
    api_key: Optional[str] = None
    system_context: Optional[str] = None
    container_id: Optional[int] = None


class ReloadProfileRequest(BaseModel):
    client_id: int
    package: Optional[str] = None


async def verify_auth(x_api_key: str = Header(None, alias="x-api-key")):
    if x_api_key != GATEWAY_AUTH:
        raise HTTPException(status_code=401)


@app.get("/health")
async def health():
    return {"status": "ok", "gateway": "hermes", "version": "2.1.0"}


@app.post("/api/chat/send")
async def chat_send(req: ChatRequest):
    cid = req.client_id
    await security.enforce_all(cid, "llm_call", content=req.content)

    if not await rate_limiter.check(cid):
        return {"success": False, "error": "rate_limited"}
    if await rate_limiter.is_exhausted(cid):
        return {"success": False, "error": "token_quota_exceeded"}

    try:
        result = await request_queue.enqueue(
            cid,
            _call_llm(cid, req.content, req.provider, req.model, req.api_key, req.system_context)
        )
        await security.audit(cid, "chat", "success")
        return result
    except TimeoutError:
        return {"success": False, "error": "timeout"}


async def _call_llm(client_id, content, provider="mimo", model=None, api_key=None, system_ctx=None):
    cfg = PROVIDERS.get(provider, PROVIDERS["mimo"])
    key = api_key or cfg["api_key"]
    model = model or cfg["default_model"]

    soul = _load_soul(client_id)
    messages = []
    if soul:
        messages.append({"role": "system", "content": soul[:2000]})
    if system_ctx:
        messages.append({"role": "system", "content": system_ctx})
    messages.append({"role": "user", "content": content})

    try:
        async with httpx.AsyncClient(timeout=120) as cl:
            r = await cl.post(
                cfg["base_url"] + "/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.7, "stream": False},
                headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + key} if key else {})} 
            )
        if r.status_code != 200:
            return {"success": False, "error": f"LLM {r.status_code}", "message": r.text[:300]}

        data = r.json()
        reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        it = usage.get("prompt_tokens", 0)
        ot = usage.get("completion_tokens", 0)
        await rate_limiter.record(client_id, it + ot)

        return {"success": True, "content": reply, "model": model, "provider": provider,
                "input_tokens": it, "output_tokens": ot, "tokens_used": it + ot}
    except httpx.TimeoutException:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": "llm_error", "message": str(e)[:200]}


def _load_soul(client_id):
    path = os.path.join(PROFILES_DIR, f"client_{client_id}", "SOUL.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()[:2000]
    return ""


@app.get("/api/chat/history")
async def chat_history(client_id: int, limit: int = 10):
    return {"client_id": client_id, "messages": []}


@app.get("/api/v1/admin/stats")
async def admin_stats():
    return {"profiles": len([d for d in os.listdir(PROFILES_DIR) if d.startswith("client_")])}


# ── Hot-Reload Endpoints ──────────────────────────────────────────

@app.post("/admin/reload-profile")
async def reload_profile(req: ReloadProfileRequest):
    """Hot-reload a client profile without restarting gateway."""
    cid = req.client_id

    package = req.package
    if not package:
        config_path = os.path.join(PROFILES_DIR, f"client_{cid}", "config.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = yaml.safe_load(f)
            package = config.get("client", {}).get("package", "basic")
        else:
            return {"success": False, "error": "profile_not_found"}

    await rate_limiter.set_package(cid, package)
    await request_queue.set_package(cid, package)

    limits = rate_limiter.buckets.get(cid)
    stats = limits.stats if limits else {}

    return {
        "success": True,
        "client_id": cid,
        "package": package,
        "limits": stats,
    }


@app.put("/admin/reload-profile/batch")
async def reload_profiles_batch(client_ids: list[int]):
    """Hot-reload multiple profiles (for package edit affecting many users)."""
    results = []
    for cid in client_ids:
        config_path = os.path.join(PROFILES_DIR, f"client_{cid}", "config.yaml")
        if not os.path.exists(config_path):
            results.append({"client_id": cid, "success": False, "error": "profile_not_found"})
            continue

        with open(config_path) as f:
            config = yaml.safe_load(f)
        package = config.get("client", {}).get("package", "basic")

        await rate_limiter.set_package(cid, package)
        await request_queue.set_package(cid, package)

        results.append({"client_id": cid, "package": package, "success": True})

    return {"success": True, "results": results, "count": len(results)}
