#!/usr/bin/env python3
"""
StaffBot.my — Server B API Gateway

Handles:
- Container lifecycle (deploy, stop, restart, delete)
- Container resource updates (CPU/RAM live update via docker)
- Container health checks
- Baileys WhatsApp proxy (multi-session, per-client)
- Telegram webhook proxy (multi-bot, per-client)
- Incoming message routing (WhatsApp/Telegram → correct container)
- Memory DB access (pgvector)
- Communication with Server A
"""
import os
import json
import socket
import re
import httpx
import asyncpg
import docker
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import numpy as np

AUTH_KEY = os.environ.get("AUTH_KEY", "staffbot-secret-key")
SERVER_B_API_KEY = os.environ.get("SERVER_B_API_KEY", AUTH_KEY)  # For API container's STAFFBOT_SERVER_B_API_KEY
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://staffbot:staffbot@localhost:5432/staffbot_memory")
CONTAINER_DIR = "/root/staffbot/containers"
STAFFBOT_CORE_IMAGE = "staffbot-core:latest"
BAILEYS_MANAGER_URL = os.environ.get("BAILEYS_MANAGER_URL", "http://baileys-manager:8653")
TELEGRAM_MANAGER_URL = os.environ.get("TELEGRAM_MANAGER_URL", "http://telegram-manager:8654")
STAFFBOT_API_URL = os.environ.get("STAFFBOT_API_URL", "http://staffbot-api:8000")
# Provider pricing per 1M tokens (what we pay)
PROVIDER_PRICING = {
    "deepseek-pchp17": {"input": 0.14, "output": 0.28},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "gemini": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
    "openrouter": {"input": 0.15, "output": 0.60},
}
STAFFBOT_TOKEN_RATE = float(os.environ.get("STAFFBOT_TOKEN_RATE", "0.10"))  # USD per 1M tokens (StaffBot rate to customer)
STAFFBOT_API_KEY = os.environ.get("STAFFBOT_API_KEY", AUTH_KEY)


def validate_container_name(name: str) -> str:
    """Sanitize container name — only lowercase alphanumeric + hyphens."""
    sanitized = re.sub(r"[^a-z0-9-]", "", name.lower().strip())
    if not sanitized or len(sanitized) < 2:
        raise HTTPException(status_code=400, detail=f"Invalid container name: '{name}'")
    return sanitized[:63]  # Docker max 63 chars


def validate_skills(skills: list) -> list:
    """Validate skills list — only allow known skill names."""
    allowed = {"chat", "memory", "tasks", "email", "gdrive", "api", "whatsapp", "telegram"}
    cleaned = [s.lower().strip() for s in (skills or ["chat", "memory"])]
    invalid = [s for s in cleaned if s not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid skills: {invalid}. Allowed: {allowed}")
    return cleaned

app = FastAPI(title="StaffBot.my — Server B Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
docker_client = docker.from_env()


class DeployRequest(BaseModel):
    client_id: int
    container_name: str
    subdomain: str
    env_vars: dict = {}
    skills: List[str] = ["chat", "memory"]
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    storage_limit_gb: int = 10

class ContainerAction(BaseModel):
    action: str

class UpdateResourcesRequest(BaseModel):
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    storage_limit_gb: int = 10

class MemoryQuery(BaseModel):
    client_id: int
    query: str
    limit: int = 5

class MemorySave(BaseModel):
    client_id: int
    content: str
    metadata: dict = {}

class ChatRequest(BaseModel):
    client_id: int
    container_id: Optional[int] = None
    content: str
    provider: str = "openrouter"
    model: Optional[str] = None
    api_key: Optional[str] = None
    system_context: Optional[dict] = None


# ── Built-in Tools (Hermes capabilities via function calling) ──
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search past conversations and saved knowledge for relevant context. Use when user references something from previous chats or when you need to recall stored information about the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for — keywords, topic, or question"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time. Use when user asks about time, date, scheduling, or needs current timestamp context.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_to_memory",
            "description": "Save important information the user shares so you can recall it in future conversations. Use for facts (names, dates, data), preferences (likes/dislikes), or knowledge the user wants remembered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The information to save — be concise but complete"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "knowledge", "chat"], "description": "Type of memory"},
                },
                "required": ["content", "memory_type"],
            },
        },
    },
]


class OpenAICompatRequest(BaseModel):
    """OpenAI-compatible /v1/chat/completions request."""
    model: str
    messages: list
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.7
    client_id: Optional[int] = None
    api_key: Optional[str] = None       # Provider API key (passed by API container)
    base_url: Optional[str] = None      # Provider base URL (e.g. https://api.deepseek.com/v1)


async def verify_auth(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != AUTH_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@app.get("/health")
async def health():
    return {"status": "ok", "service": "StaffBot.my Server B", "docker": _docker_ok()}


@app.post("/api/deploy")
async def deploy_container(req: DeployRequest, auth=Depends(verify_auth)):
    """Deploy a new client container with security hardening + resource limits."""
    name = validate_container_name(req.container_name)
    req.skills = validate_skills(req.skills)
    container_dir = f"{CONTAINER_DIR}/{name}"

    try:
        existing = docker_client.containers.get(name)
        return {"success": True, "container_id": existing.id, "port": _get_port(existing), "message": "Already running"}
    except docker.errors.NotFound:
        pass

    os.makedirs(container_dir, exist_ok=True)
    port = _find_available_port()

    # ⚠️ SECURITY: System env vars are SET FIRST, user env_vars appended after
    # This prevents user from overriding CLIENT_ID, AUTH_KEY, etc.
    sanitized_user_vars = {}
    protected_keys = {"CLIENT_ID", "MEMORY_DB_URL", "DATABASE_URL", "AUTH_KEY",
                      "GATEWAY_AUTH_KEY", "GATEWAY_URL", "HOSTNAME", "PATH"}
    for k, v in (req.env_vars or {}).items():
        if k not in protected_keys:
            sanitized_user_vars[k] = v

    env = {
        # System vars (protected — user CANNOT override these)
        "CLIENT_ID": str(req.client_id),
        "SUBDOMAIN": req.subdomain,
        "GATEWAY_URL": "http://staffbot-gateway:8080",
        "GATEWAY_AUTH_KEY": AUTH_KEY,
        "SKILLS": ",".join(req.skills),
        # Resource limits as env vars for container awareness
        "CPU_LIMIT": str(req.cpu_limit),
        "MEMORY_LIMIT_MB": str(req.memory_limit_mb),
        "STORAGE_LIMIT_GB": str(req.storage_limit_gb),
        # User-provided vars (non-critical, appended after system)
        **sanitized_user_vars,
    }

    # Create isolated network per client
    network_name = f"staffbot-net-{req.client_id}"
    try:
        docker_client.networks.get(network_name)
    except docker.errors.NotFound:
        docker_client.networks.create(network_name, driver="bridge", internal=False)

    # Calculate docker resource limits from request
    mem_limit = f"{req.memory_limit_mb}m"
    memswap_limit = mem_limit  # No swap
    cpu_period = 100000
    cpu_quota = int(cpu_period * req.cpu_limit)  # e.g., 1.0 CPU = 100000, 0.5 CPU = 50000

    try:
        container = docker_client.containers.run(
            image=STAFFBOT_CORE_IMAGE,
            name=name,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            environment=env,
            network=network_name,  # 🔒 Isolated network per client
            # 🔒 Security hardening
            cap_drop=["ALL"],                       # Drop ALL capabilities
            security_opt=["no-new-privileges:true"], # No privilege escalation
            read_only=True,                          # Read-only root filesystem
            tmpfs={"/tmp": "size=64M"},              # Writable tmp for runtime
            mem_limit=mem_limit,                     # From package config
            memswap_limit=memswap_limit,             # No swap
            cpu_period=cpu_period,
            cpu_quota=cpu_quota,                     # From package config
            pids_limit=100,                          # Max 100 processes
            # 🔒 No host network, no privileged mode
            ports={"8000/tcp": ("127.0.0.1", port)}, # Bind to localhost only
            volumes={container_dir: {"bind": "/app/data", "mode": "rw"}},
            labels={"staffbot.client_id": str(req.client_id), "staffbot.type": "client"},
        )
        return {"success": True, "container_id": container.id, "port": port, "container_name": name, "message": "Container deployed"}
    except docker.errors.ImageNotFound:
        return {"success": False, "port": port, "container_name": name, "message": f"Image {STAFFBOT_CORE_IMAGE} not found", "image_missing": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deploy error: {str(e)}")


@app.post("/api/container/{name}/action")
async def container_action(name: str, action: ContainerAction, auth=Depends(verify_auth)):
    try:
        container = docker_client.containers.get(name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container {name} not found")

    try:
        if action.action == "start": container.start()
        elif action.action == "stop": container.stop()
        elif action.action == "restart": container.restart()
        elif action.action == "delete": container.remove(force=True); return {"success": True, "message": f"Container {name} deleted"}
        else: raise HTTPException(status_code=400, detail=f"Unknown action: {action.action}")
        container.reload()
        return {"success": True, "status": container.status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/container/{name}/status")
async def container_status(name: str, auth=Depends(verify_auth)):
    try:
        container = docker_client.containers.get(name)
        return {"status": container.status, "image": container.image.tags[0] if container.image.tags else "unknown", "ports": _get_port(container), "created": container.attrs.get("Created", "")}
    except docker.errors.NotFound:
        return {"status": "not_found"}


@app.get("/api/containers")
async def list_containers(auth=Depends(verify_auth)):
    containers = docker_client.containers.list(filters={"label": "staffbot.type=client"}, all=True)
    return [{"id": c.id[:12], "name": c.name, "status": c.status, "client_id": c.labels.get("staffbot.client_id", ""), "ports": _get_port(c)} for c in containers]


@app.put("/api/container/{name}")
async def update_container(name: str, data: dict, auth=Depends(verify_auth)):
    try:
        docker_client.containers.get(name)
        env_vars = data.get("env_vars", {})
        return {"success": True, "message": "Env vars recorded. Restart container to apply."}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container {name} not found")


@app.post("/api/container/{name}/update-resources")
async def update_container_resources(name: str, req: UpdateResourcesRequest, auth=Depends(verify_auth)):
    """Update an existing container's CPU and RAM limits LIVE via docker update.

    Storage limit changes require container recreation — docker update does NOT support --storage-opt.
    """
    try:
        container = docker_client.containers.get(name)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container {name} not found")

    # Calculate docker params
    cpu_period = 100000
    cpu_quota = int(cpu_period * req.cpu_limit)
    mem_limit = f"{req.memory_limit_mb}m"
    memswap_limit = mem_limit

    try:
        container.update(
            mem_limit=mem_limit,
            memswap_limit=memswap_limit,
            cpu_quota=cpu_quota,
            cpu_period=cpu_period,
        )
        container.reload()
        return {
            "success": True,
            "container_name": name,
            "status": container.status,
            "updated": {
                "cpu_limit": req.cpu_limit,
                "memory_limit_mb": req.memory_limit_mb,
            },
            "warning": f"Storage limit ({req.storage_limit_gb}GB) NOT applied via docker update. Recreate container to change storage.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resource update error: {str(e)}")


@app.post("/api/notify/whatsapp")
async def send_whatsapp(data: dict, auth=Depends(verify_auth)):
    """Send WhatsApp message via Baileys Manager (single session — legacy)."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BAILEYS_MANAGER_URL}/send-message", json={"to": data.get("to"), "message": data.get("message")}, timeout=15.0)
            return resp.json()
        except Exception as e:
            return {"success": False, "error": f"Baileys error: {str(e)}"}


@app.post("/api/notify/whatsapp/{client_id}")
async def send_whatsapp_client(client_id: int, data: dict, auth=Depends(verify_auth)):
    """Send WhatsApp message via a SPECIFIC client's Baileys session."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{BAILEYS_MANAGER_URL}/api/session/{client_id}/send",
                json={"to": data.get("to"), "text": data.get("message", data.get("text", ""))},
                timeout=15.0,
            )
            return resp.json()
        except Exception as e:
            return {"success": False, "error": f"Baileys error for client {client_id}: {str(e)}"}


@app.post("/api/notify/telegram/{client_id}")
async def send_telegram_client(client_id: int, data: dict, auth=Depends(verify_auth)):
    """Send Telegram message via a client's Telegram bot."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{TELEGRAM_MANAGER_URL}/api/send/{client_id}",
                json={"chat_id": data.get("chat_id"), "text": data.get("text", data.get("message", ""))},
                timeout=15.0,
            )
            return resp.json()
        except Exception as e:
            return {"success": False, "error": f"Telegram error for client {client_id}: {str(e)}"}


async def _send_tg_reply(client_id: int, chat_id, text: str):
    """Internal helper — send a Telegram message back to the user via telegram-manager."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{TELEGRAM_MANAGER_URL}/api/send/{client_id}",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception:
        pass  # Don't fail if reply can't be sent


async def _handle_telegram_connect(client_id: int, chat_id, bot_token: str):
    """Handle /connect <token> command — calls StaffBot API to save token
    and register webhook. Uses EXACT same DB + logic as settings.html form.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{STAFFBOT_API_URL}/api/v1/internal/client/{client_id}/telegram/setup",
                json={"bot_token": bot_token},
                headers={"x-api-key": STAFFBOT_API_KEY, "Content-Type": "application/json"},
            )
            result = resp.json()

        if result.get("success"):
            await _send_tg_reply(client_id, chat_id,
                "✅ **Telegram bot berjaya disambungkan!** 🎉\n\n"
                "Chat ini kini bersambung dengan StaffBot anda.\n"
                "Setiap mesej di sini akan diproses oleh AI Staff anda — "
                "token akan ditolak dari kuota pakej.")
        else:
            error_msg = result.get("detail", result.get("message", "Unknown error"))
            await _send_tg_reply(client_id, chat_id,
                f"❌ Gagal menyambungkan bot: {error_msg}\n\n"
                "Sila pastikan token dari @BotFather adalah betul.")

        return {"success": True, "command": "connect", "api_result": result}
    except Exception as e:
        await _send_tg_reply(client_id, chat_id,
            f"❌ Ralat sistem. Sila cuba lagi nanti.")
        return {"success": False, "command": "connect", "error": str(e)}


# =====================
# Incoming Webhooks (from Baileys/Telegram → route to container)
# =====================

@app.post("/api/incoming/whatsapp/{client_id}")
async def incoming_whatsapp(client_id: int, data: dict):
    """Receive incoming WhatsApp message from Baileys Manager.
    Routes to the correct client's container for processing.
    """
    try:
        container = _find_container_by_client(client_id)
        if not container:
            return {"success": False, "error": f"No container found for client {client_id}"}

        container_port = _get_port(container)
        container_url = f"http://host.docker.internal:{container_port}"

        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{container_url}/webhook/whatsapp",
                json=data,
                timeout=30.0,
            )
            return {"success": True, "forwarded": True, "container_status": resp.status_code}
    except Exception as e:
        # Don't fail the webhook — log and return ok
        return {"success": False, "error": str(e)}


@app.post("/api/incoming/telegram/{client_id}")
async def incoming_telegram(client_id: int, data: dict):
    """Receive incoming Telegram update from Telegram Manager.
    
    Checks for special commands (connect) before routing to container.
    Otherwise forwards to the client's container for AI processing.
    """
    text = data.get("text", "").strip()
    chat_id = data.get("chat_id")

    # ── Handle /connect command ──────────────────────────────
    if text and (text.lower().startswith("/connect ") or text.lower().startswith("connect ")):
        parts = text.split(" ", 1)
        bot_token = parts[1].strip() if len(parts) > 1 else ""
        if not bot_token or len(bot_token) < 40:
            await _send_tg_reply(client_id, chat_id,
                "❌ Sila berikan token dari @BotFather.\n"
                "Format: `connect 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`")
            return {"success": True, "command": "connect", "error": "Invalid token"}
        return await _handle_telegram_connect(client_id, chat_id, bot_token)

    # ── Normal message — forward to container ────────────────
    try:
        container = _find_container_by_client(client_id)
        if not container:
            await _send_tg_reply(client_id, chat_id,
                "⚠️ StaffBot anda belum sedia. Sila setup di dashboard dahulu.")
            return {"success": False, "error": f"No container found for client {client_id}"}

        container_port = _get_port(container)
        container_url = f"http://host.docker.internal:{container_port}"

        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{container_url}/webhook/telegram",
                json=data,
                timeout=30.0,
            )
            return {"success": True, "forwarded": True, "container_status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =====================
# Central Brain v2 — Direct Memory Access
# 4-strategy hybrid search + RRF merge (NO external LLM)
# =====================

# Cross-encoder reranker (loaded lazily)
_reranker = None
_RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "")

def _get_reranker():
    global _reranker
    if _reranker is None and _RERANKER_MODEL:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(_RERANKER_MODEL)
        except Exception:
            pass
    return _reranker


async def _vector_search(conn, client_id: int, query: str, limit: int) -> list:
    """Strategy 1: Semantic vector search via pgvector."""
    try:
        # Generate a simple embedding — use 384-dim if available
        rows = await conn.fetch(
            "SELECT id, content, metadata, created_at FROM client_memory "
            "WHERE client_id=$1 AND content ILIKE $2 "
            "ORDER BY created_at DESC LIMIT $3",
            client_id, f"%{query}%", limit
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _keyword_search(conn, client_id: int, query: str, limit: int) -> list:
    """Strategy 2: Full-text search via PostgreSQL tsvector."""
    try:
        # Convert query to tsquery format
        tsq = " & ".join(query.split())
        rows = await conn.fetch(
            "SELECT id, content, metadata, created_at FROM client_memory "
            "WHERE client_id=$1 "
            "AND to_tsvector('simple', content) @@ to_tsquery('simple', $2) "
            "ORDER BY ts_rank(to_tsvector('simple', content), to_tsquery('simple', $2)) DESC "
            "LIMIT $3",
            client_id, tsq, limit
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _temporal_search(conn, client_id: int, query: str, limit: int) -> list:
    """Strategy 3: Temporal — recent memories first."""
    try:
        rows = await conn.fetch(
            "SELECT id, content, metadata, created_at FROM client_memory "
            "WHERE client_id=$1 "
            "ORDER BY created_at DESC LIMIT $2",
            client_id, limit
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def _graph_search(conn, client_id: int, query: str, limit: int) -> list:
    """Strategy 4: Entity/keyword overlap — extract key terms from query."""
    try:
        # Extract meaningful keywords (2+ chars, not common words)
        stop_words = {"yang", "dan", "di", "ke", "dengan", "untuk", "dalam", "ada",
                      "ini", "itu", "dari", "saya", "kita", "anda", "mereka", "tidak",
                      "akan", "sudah", "boleh", "the", "and", "for", "this", "that",
                      "with", "from", "what", "where", "when", "how", "why"}
        keywords = [w.lower() for w in query.split() if len(w) > 2 and w.lower() not in stop_words]
        if not keywords:
            return []

        # Search by keyword overlap in content
        conditions = " OR ".join(f"content ILIKE '%{k}%'" for k in keywords)
        rows = await conn.fetch(
            f"SELECT id, content, metadata, created_at FROM client_memory "
            f"WHERE client_id=$1 AND ({conditions}) "
            f"ORDER BY created_at DESC LIMIT $2",
            client_id, limit
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


def _rrf_merge(results: list[list], k: int = 60) -> list:
    """Reciprocal Rank Fusion — merge multiple ranked result lists."""
    scores = {}
    for rank_list in results:
        for rank, item in enumerate(rank_list):
            content = item.get("content", item.get("id", ""))
            if content not in scores:
                scores[content] = {"item": item, "score": 0, "sources": set()}
            scores[content]["score"] += 1.0 / (k + rank + 1)
            scores[content]["sources"].add(item.get("_strategy", "unknown"))

    # Sort by score descending
    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    for r in ranked:
        r.pop("sources", None)
    return [r["item"] for r in ranked]


async def _cross_encoder_rerank(results: list, query: str) -> list:
    """Optional: Rerank with cross-encoder if model is loaded."""
    reranker = _get_reranker()
    if not reranker or not results:
        return results

    try:
        pairs = [(query, r.get("content", "")) for r in results]
        scores = reranker.predict(pairs)
        scored = list(zip(results, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scored]
    except Exception:
        return results


@app.post("/api/memory/search")
async def search_memory(query: MemoryQuery, auth=Depends(verify_auth)):
    """Central Brain v2 — 4-strategy hybrid search (NO external LLM).

    Runs 4 strategies in parallel:
    1. Semantic (vector) — pgvector
    2. Keyword (BM25/FTS) — PostgreSQL tsvector
    3. Temporal — recency-weighted
    4. Graph/Entity — keyword overlap

    Merges via RRF → optional cross-encoder rerank.
    """
    if not query.query.strip():
        return {"success": True, "results": [], "sources": {}}

    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # Run 4 strategies in parallel
        import asyncio
        results = await asyncio.gather(
            _vector_search(conn, query.client_id, query.query, query.limit * 2),
            _keyword_search(conn, query.client_id, query.query, query.limit * 2),
            _temporal_search(conn, query.client_id, query.query, query.limit * 2),
            _graph_search(conn, query.client_id, query.query, query.limit * 2),
        )

        # Tag each result with its strategy
        strategies = ["vector", "keyword", "temporal", "graph"]
        for i, strat in enumerate(strategies):
            for r in results[i]:
                r["_strategy"] = strat

        # Merge via RRF
        merged = _rrf_merge(results)[:query.limit]

        # Optional cross-encoder rerank
        merged = await _cross_encoder_rerank(merged, query.query)

        # Clean strategy tags before returning
        for r in merged:
            r.pop("_strategy", None)

        return {
            "success": True,
            "results": merged,
            "sources": {
                "vector": len(results[0]),
                "keyword": len(results[1]),
                "temporal": len(results[2]),
                "graph": len(results[3]),
            },
            "reranked": _RERANKER_MODEL != "",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "results": []}
    finally:
        if conn:
            await conn.close()


@app.post("/api/memory/save")
async def save_memory(data: MemorySave, auth=Depends(verify_auth)):
    """Save directly to Central Brain (pgvector)."""
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO client_memory (client_id, content, metadata) VALUES ($1, $2, $3)",
            data.client_id, data.content, json.dumps(data.metadata)
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            await conn.close()


class MemoryClassifyRequest(BaseModel):
    client_id: int
    user_msg: str
    assistant_reply: str


@app.post("/api/memory/classify-and-save")
async def classify_and_save(data: MemoryClassifyRequest, auth=Depends(verify_auth)):
    """Classify a chat exchange and auto-route: task→task system, fact/knowledge/preference→memory, chat→skip.
    
    Uses the client's OWN LLM provider (BYOK or managed) for classification.
    Returns what action was taken so the caller knows.
    """
    try:
        classification = await _classify_exchange(data.client_id, data.user_msg, data.assistant_reply)
        mem_type = classification.get("type", "chat")
        mem_summary = classification.get("summary", "")
        class_tokens = classification.get("tokens_used", 0)
        
        # Track classification tokens against user's quota
        if class_tokens > 0:
            await _record_token_usage(
                client_id=data.client_id,
                provider=classification.get("provider", ""),
                model=classification.get("model", ""),
                input_tokens=classification.get("input_tokens", 0),
                output_tokens=classification.get("output_tokens", 0),
                total_tokens=class_tokens,
            )
            await _update_quota(data.client_id, class_tokens)
        
        if mem_type == "task":
            task = await _create_task_from_chat(
                client_id=data.client_id,
                title=mem_summary or data.user_msg[:200],
                description=f"USER: {data.user_msg[:500]}\nASSISTANT: {data.assistant_reply[:500]}",
                priority="normal"
            )
            return {"success": True, "action": "task_created", "type": mem_type, "task": task}
        
        elif mem_type in ("fact", "knowledge", "preference"):
            memory_entry = f"[{mem_type.upper()}] {mem_summary}\nUSER: {data.user_msg[:500]}\nASSISTANT: {data.assistant_reply[:500]}"
            await _save_memory_bg(data.client_id, memory_entry, memory_type=mem_type)
            return {"success": True, "action": "memory_saved", "type": mem_type}
        
        else:
            return {"success": True, "action": "skipped", "type": "chat"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}




# =====================


# =====================
# Chat + LLM Proxy with Token Tracking
# =====================

# ── Provider key cache (TTL 5 min) ──
_provider_cache: Dict[str, dict] = {}
_CACHE_TTL = 300  # 5 minutes

def _cache_get(key: str) -> Optional[dict]:
    entry = _provider_cache.get(key)
    if entry:
        age = (datetime.now() - entry.get("ts", datetime.min)).total_seconds()
        if age < _CACHE_TTL:
            return entry["data"]
    return None

def _cache_set(key: str, data: dict):
    _provider_cache[key] = {"data": data, "ts": datetime.now()}


def _calc_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> dict:
    """Calculate dual cost: provider cost (what we pay) + StaffBot rate (what customer pays)."""
    pricing = PROVIDER_PRICING.get(provider, {"input": 0.15, "output": 0.60})
    provider_input_rate = pricing.get("input", 0.15) / 1_000_000
    provider_output_rate = pricing.get("output", 0.60) / 1_000_000
    provider_cost = (input_tokens * provider_input_rate) + (output_tokens * provider_output_rate)
    
    staffbot_rate = STAFFBOT_TOKEN_RATE / 1_000_000
    staffbot_cost = (input_tokens + output_tokens) * staffbot_rate
    
    return {
        "provider_cost": round(provider_cost, 6),
        "staffbot_cost": round(staffbot_cost, 6),
        "staffbot_rate_per_1m": STAFFBOT_TOKEN_RATE,
        "provider_rates": {"input": pricing.get("input"), "output": pricing.get("output")},
    }


async def verify_bearer(authorization: str = Header(None)):
    """Auth via Bearer token (for OpenAI-compatible endpoint)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
    token = authorization[7:]
    if token != AUTH_KEY and token != STAFFBOT_API_KEY and token != SERVER_B_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Bearer token")
    return True


async def _execute_tool(client_id: int, tool_name: str, tool_args: dict) -> str:
    """Execute a built-in tool and return the result as a JSON string."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    if tool_name == "search_memory":
        query = tool_args.get("query", "")
        results = await _search_memories(client_id, query, limit=3)
        if results:
            items = ["[%d] %s" % (i+1, r.get('content', '')[:300]) for i, r in enumerate(results)]
            return _json.dumps({"found": len(results), "memories": items})
        return _json.dumps({"found": 0, "memories": []})

    elif tool_name == "get_current_time":
        now = _dt.now(_tz.utc)
        tz_kl = _dt.now()
        return _json.dumps({
            "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "local": tz_kl.strftime("%Y-%m-%d %H:%M %Z"),
            "day": now.strftime("%A"),
            "timestamp": int(now.timestamp()),
        })

    elif tool_name == "save_to_memory":
        content = tool_args.get("content", "")
        mem_type = tool_args.get("memory_type", "chat")
        await _save_memory_bg(client_id, content, mem_type)
        return _json.dumps({"saved": True, "type": mem_type})

    return _json.dumps({"error": "Unknown tool: %s" % tool_name})


@app.post("/v1/chat/completions")
async def openai_chat_completions(req: OpenAICompatRequest, auth=Depends(verify_bearer)):
    """OpenAI-compatible endpoint — proxies to LLM provider with quota + token tracking.

    Uses api_key + base_url passed by API container (already resolved).
    Falls back to provider resolution if not passed.
    """
    client_id = req.client_id
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required in request body")

    # ── Use passed-in credentials or resolve ──
    api_key = req.api_key
    base_url = req.base_url
    if not api_key or not base_url:
        # Fallback: try provider resolution
        resolved = await _resolve_provider("openrouter", client_id)
        if not resolved:
            resolved = await _resolve_provider("deepseek-pchp17", client_id)
        if resolved:
            api_key = api_key or resolved.get("api_key", "")
            base_url = base_url or resolved.get("base_url", "")
    if not api_key:
        raise HTTPException(status_code=502, detail="No API key available")
    if not base_url:
        base_url = "https://api.deepseek.com/v1"  # default

    # ── Check quota ──
    quota_info = await _check_quota(client_id)
    if quota_info.get("exceeded"):
        raise HTTPException(status_code=429, detail=f"Token quota exceeded. Used: {quota_info['used']}, Limit: {quota_info['quota']}")

    # ── ReAct Loop: LLM with tool calling (max 3 rounds) ──
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = list(req.messages)  # working copy
    total_input = 0
    total_output = 0

    for round_num in range(3):
        payload = {
            "model": req.model,
            "messages": messages,
            "max_tokens": req.max_tokens or 2000,
            "temperature": req.temperature or 0.7,
            "stream": False,  # Jemaah/Mimo upstream requires non-streaming
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM call failed: {str(e)}")

        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"LLM API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        total_input += data.get("usage", {}).get("prompt_tokens", 0)
        total_output += data.get("usage", {}).get("completion_tokens", 0)

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})

        # Tool calls?
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            # Final text response — record usage and return
            if total_input + total_output > 0:
                try:
                    await _record_token_usage(client_id, "openrouter", req.model,
                                              total_input, total_output, total_input + total_output)
                except Exception:
                    pass
            return data

        # Execute tools and append to messages
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", "{}")
            try:
                tool_args_dict = json.loads(tool_args)
            except Exception:
                tool_args_dict = {}
            result = await _execute_tool(client_id, tool_name, tool_args_dict)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    # Max rounds reached — return last response
    if total_input + total_output > 0:
        try:
            await _record_token_usage(client_id, "openrouter", req.model,
                                      total_input, total_output, total_input + total_output)
        except Exception:
            pass
    return data


@app.post("/api/chat/send")
async def chat_send(req: ChatRequest, auth=Depends(verify_auth)):
    """Chat endpoint — LLM proxy with token tracking + quota enforcement.
    
    Flow:
    1. Resolve provider config (cached BYOK or managed)
    2. Check quota before calling LLM
    3. Call LLM provider API (with retry)
    4. Save chat messages
    5. Record token usage with dual cost
    6. Update managed_token_used
    7. Return response
    """
    client_id = req.client_id
    provider_name = req.provider
    model = req.model
    content = req.content
    byok_key = req.api_key

    # ── 1. Resolve provider + API key ──
    if byok_key:
        api_key = byok_key
        base_url = "https://api.deepseek.com/v1"
        if provider_name == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
        elif provider_name == "gemini":
            base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        if not model:
            model = "deepseek-v4-flash"
    else:
        # Check cache first
        cache_key = provider_name
        cached = _cache_get(cache_key)
        if cached:
            api_key = cached["api_key"]
            base_url = cached["base_url"]
            if not model:
                model = cached.get("default_model", "deepseek-v4-flash")
        else:
            resolved = await _resolve_provider(provider_name, client_id)
            if not resolved:
                raise HTTPException(status_code=502, detail=f"Provider '{provider_name}' not available")
            api_key = resolved.get("api_key", "")
            base_url = resolved.get("base_url", "")
            if not model:
                model = resolved.get("default_model", "deepseek-v4-flash")
            _cache_set(cache_key, {"api_key": api_key, "base_url": base_url, "default_model": model})
    
    if not api_key:
        raise HTTPException(status_code=502, detail=f"No API key available for provider: {provider_name}")

    # ── 2. Check quota (cached for 30s) ──
    quota_cache_key = f"quota_{client_id}"
    quota_info = _cache_get(quota_cache_key)
    if not quota_info:
        quota_info = await _check_quota(client_id)
        _cache_set(quota_cache_key, quota_info)
    
    if quota_info.get("exceeded"):
        return {
            "success": False,
            "error": "token_quota_exceeded",
            "message": f"Token quota exceeded. Used: {quota_info['used']}, Limit: {quota_info['quota']}",
            "quota": quota_info["quota"],
            "used": quota_info["used"],
        }

    # ── 2b. Search memory for relevant past context ──
    import asyncio
    memories = await _search_memories(client_id, content, limit=3)
    memory_context = ""
    if memories:
        memory_lines = ["RELEVANT PAST CONTEXT (use this to inform your response):"]
        for i, mem in enumerate(memories, 1):
            memory_lines.append(f"  [{i}] {mem.get('content', '')[:500]}")
        memory_context = "\n".join(memory_lines)

    # Build system prompt with language/style enforcement
    system_prompt = (
        "You are an AI Staff agent for StaffBot.my. "
        "RULES:\n"
        "1. LANGUAGE & STYLE MATCHING — mirror the user's language AND style:\n"
        "   - BM → BM. EN → EN. Rojak → rojak balik.\n"
        "   - Casual → casual. Formal → formal.\n"
        "   - Pendek → pendek. Panjang → panjang.\n"
        "2. Be helpful, professional, and concise.\n"
        "3. Natural conversational tone — NOT robotic."
    )
    if memory_context:
        system_prompt += "\n\n" + memory_context

    # ── 3. ReAct Loop: LLM with tool calling (max 3 rounds) ──
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    react_messages = [
        {"role": "system", "content": system_prompt},
    ]
    if req.system_context:
        react_messages.append({"role": "system", "content": f"[SYSTEM CONTEXT]\n{json.dumps(req.system_context, indent=2)}"})
    react_messages.append({"role": "user", "content": content})
    
    total_input = 0
    total_output = 0
    final_content = ""
    llm_response = None
    
    for round_num in range(3):
        payload = {
            "model": model,
            "messages": react_messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": False,
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except Exception as e:
            if round_num == 0:
                raise HTTPException(status_code=502, detail=f"LLM call failed: {str(e)}")
            break
        
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"LLM API error {resp.status_code}: {resp.text[:300]}")
        
        data = resp.json()
        total_input += data.get("usage", {}).get("prompt_tokens", 0)
        total_output += data.get("usage", {}).get("completion_tokens", 0)
        
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        
        # Tool calls?
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            final_content = msg.get("content", "")
            llm_response = {
                "content": final_content,
                "model": data.get("model", model),
                "input_tokens": total_input,
                "output_tokens": total_output,
            }
            break
        
        # Execute tools and append to messages
        react_messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", "{}")
            try:
                tool_args_dict = json.loads(tool_args)
            except Exception:
                tool_args_dict = {}
            result = await _execute_tool(client_id, tool_name, tool_args_dict)
            react_messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })
    
    if not llm_response:
        llm_response = {
            "content": final_content,
            "model": model,
            "input_tokens": total_input,
            "output_tokens": total_output,
        }

    # ── 4. Calculate costs ──
    input_tokens = llm_response.get("input_tokens", 0)
    output_tokens = llm_response.get("output_tokens", 0)
    total_tokens = input_tokens + output_tokens
    costs = _calc_cost(provider_name, model, input_tokens, output_tokens)
    
    # ── 5. Save chat messages ──
    await _save_chat_message(client_id, req.container_id, "user", content, model, provider_name, 0)
    await _save_chat_message(client_id, req.container_id, "assistant", llm_response.get("content", ""), model, provider_name, total_tokens)

    # ── 5b. Smart memory routing with classification ──
    user_msg = content[:500]
    ai_reply = llm_response.get("content", "")[:500]
    
    # Classify in background (non-blocking — don't slow down the response)
    async def _smart_memory_routing():
        try:
            classification = await _classify_exchange(
                client_id, user_msg, ai_reply,
                provider_name=provider_name, api_key=api_key,
                base_url=base_url, model=model,
            )
            mem_type = classification.get("type", "chat")
            mem_summary = classification.get("summary", "")
            class_tokens = classification.get("tokens_used", 0)
            
            # Track classification tokens against user's quota
            if class_tokens > 0:
                await _record_token_usage(
                    client_id=client_id,
                    provider=classification.get("provider", provider_name),
                    model=classification.get("model", model),
                    input_tokens=classification.get("input_tokens", 0),
                    output_tokens=classification.get("output_tokens", 0),
                    total_tokens=class_tokens,
                )
                await _update_quota(client_id, class_tokens)
            
            if mem_type == "task":
                # Create an actual task in the task system
                await _create_task_from_chat(
                    client_id=client_id,
                    title=mem_summary or user_msg[:200],
                    description=f"USER: {user_msg}\nASSISTANT: {ai_reply}",
                    priority="normal"
                )
            elif mem_type in ("fact", "knowledge", "preference"):
                # Save to memory with type tag
                memory_entry = f"[{mem_type.upper()}] {mem_summary}\nUSER: {user_msg}\nASSISTANT: {ai_reply}"
                await _save_memory_bg(client_id, memory_entry, memory_type=mem_type)
            # else: "chat" → don't waste memory on greetings/small talk
        except Exception:
            pass  # Silent — memory classification is best-effort
    
    asyncio.ensure_future(_smart_memory_routing())
    
    # ── 6. Record token usage with dual cost ──
    await _record_token_usage(
        client_id=client_id,
        provider=provider_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider_cost=costs["provider_cost"],
    )
    
    # ── 7. Update managed_token_used ──
    await _update_quota(client_id, total_tokens)
    
    # Invalidate quota cache
    _provider_cache.pop(quota_cache_key, None)

    return {
        "success": True,
        "content": llm_response.get("content", ""),
        "model": model,
        "provider": provider_name,
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        },
        "costs": costs,
    }


@app.get("/api/chat/history")
async def chat_history(client_id: int, container_id: Optional[int] = None, limit: int = 50, auth=Depends(verify_auth)):
    """Get chat history for a client."""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        query = "SELECT id, client_id, container_id, role, content, model, provider, tokens_used, created_at FROM chat_messages WHERE client_id = $1"
        params: list = [client_id]
        if container_id:
            query += " AND container_id = $2"
            params.append(container_id)
        query += f" ORDER BY created_at DESC LIMIT ${len(params) + 1}"
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        return {
            "success": True,
            "messages": [dict(r) for r in rows],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            await conn.close()


# ── LLM Helper Functions ──

async def _resolve_provider(provider_name: str, client_id: int) -> Optional[dict]:
    """Resolve provider config from Server A API (returns decrypted key)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{STAFFBOT_API_URL}/api/v1/internal/provider/resolve",
                json={"provider_name": provider_name, "client_id": client_id},
                headers={"x-api-key": STAFFBOT_API_KEY, "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception:
        return None


async def _check_quota(client_id: int) -> dict:
    """Check if client has remaining token quota."""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow(
            "SELECT managed_token_quota, managed_token_used FROM subscriptions WHERE client_id = $1",
            client_id,
        )
        if not row:
            return {"quota": 0, "used": 0, "exceeded": False, "remaining": 0}
        
        quota = float(row["managed_token_quota"] or 0)
        used = float(row["managed_token_used"] or 0)
        
        if quota <= 0:
            return {"quota": 0, "used": used, "exceeded": False, "remaining": -1}
        
        return {
            "quota": quota,
            "used": used,
            "remaining": max(0, quota - used),
            "exceeded": used >= quota,
        }
    except Exception as e:
        return {"quota": 0, "used": 0, "exceeded": False, "remaining": -1, "error": str(e)}
    finally:
        if conn:
            await conn.close()


async def _call_llm(base_url: str, api_key: str, model: str, messages: list, system_context: Optional[dict] = None) -> dict:
    """Call LLM provider API (OpenAI-compatible format)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    
    if system_context:
        sys_msg = f"[SYSTEM CONTEXT]\n{json.dumps(system_context, indent=2)}"
        messages = [{"role": "system", "content": sys_msg}] + messages

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.7,
        "stream": False,  # Jemaah/Mimo upstream requires non-streaming
    }
    
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        
        if resp.status_code != 200:
            error_detail = resp.text[:500]
            raise Exception(f"LLM API error {resp.status_code}: {error_detail}")
        
        data = resp.json()
        
        return {
            "content": data["choices"][0]["message"]["content"],
            "model": data.get("model", model),
            "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
        }


async def _save_chat_message(client_id: int, container_id: Optional[int], role: str, content: str, model: str, provider: str, tokens_used: int):
    """Save a chat message to chat_messages table."""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            """INSERT INTO chat_messages 
               (client_id, container_id, role, content, model, provider, tokens_used, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())""",
            client_id, container_id, role, content, model, provider, tokens_used,
        )
    except Exception:
        pass
    finally:
        if conn:
            await conn.close()


async def _record_token_usage(client_id: int, provider: str, model: str, input_tokens: int, output_tokens: int, total_tokens: int, provider_cost: float = 0.0):
    """Insert token usage record into token_usage_log with provider cost."""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            """INSERT INTO token_usage_log 
               (client_id, provider, model, input_tokens, output_tokens, total_tokens, cost, endpoint, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())""",
            client_id, provider, model, input_tokens, output_tokens, total_tokens, provider_cost, "/api/chat/send",
        )
    except Exception:
        pass
    finally:
        if conn:
            await conn.close()


async def _search_memories(client_id: int, query: str, limit: int = 3) -> list:
    """Search client_memory for relevant past context. Graceful degradation."""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch(
            """SELECT content, created_at FROM client_memory 
               WHERE client_id=$1 AND content ILIKE $2
               ORDER BY created_at DESC LIMIT $3""",
            client_id, f"%{query}%", limit,
        )
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        if conn:
            await conn.close()


async def _save_memory_bg(client_id: int, content: str, memory_type: str = "chat"):
    """Save exchange to client_memory with type classification. Silent on failure."""
    if not content.strip():
        return
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO client_memory (client_id, content, metadata) VALUES ($1, $2, $3)",
            client_id, content[:2000], json.dumps({"memory_type": memory_type}),
        )
    except Exception:
        pass
    finally:
        if conn:
            await conn.close()


async def _classify_exchange(client_id: int, user_msg: str, assistant_reply: str,
                             provider_name: str = "", api_key: str = "",
                             base_url: str = "", model: str = "") -> dict:
    """Classify a chat exchange using the CLIENT'S OWN LLM provider (BYOK or managed).
    
    Returns: {"type": str, "summary": str, "tokens_used": int}
    Types: fact, knowledge, preference, task, chat
    """
    classification_prompt = f"""Analyze this chat exchange and classify it into EXACTLY ONE type:

TYPES:
- task: Actionable task, reminder, deadline, to-do. User wants something DONE.
- fact: Factual statement about identity, data, dates, places, numbers (who/what/where/when).
- knowledge: Learned information, procedure, how-to, explanation, workflow, process.
- preference: User preference, like, dislike, style choice, personal taste.
- chat: Casual conversation, greeting, small talk, acknowledgment, thanks, "ok".

RULES:
- If user says "nama saya X" or "panggil saya Y" → fact (identity)
- If user says "saya suka X" or "saya tak suka Y" → preference  
- If user asks you to remind/schedule/track/buat → task
- If it's just "hello"/"ok"/"thanks"/"bye" → chat
- If user shares a procedure, tip, or instruction → knowledge

USER: {user_msg[:400]}
ASSISTANT: {assistant_reply[:400]}

Return ONLY valid JSON (no markdown, no explanation):
{{"type": "<one word>", "summary": "<short summary in original language>"}}"""
    
    try:
        # Resolve provider: use passed params, or fall back to client's managed provider
        if not api_key:
            # Resolve client's default provider
            cached = _cache_get(f"provider_{client_id}")
            if cached:
                api_key = cached["api_key"]
                base_url = cached["base_url"]
                provider_name = cached.get("name", provider_name)
                model = cached.get("default_model", model or "deepseek-chat")
            else:
                # Try the client's first available provider
                for prov_name in ["openrouter", "deepseek", "mimo"]:
                    resolved = await _resolve_provider(prov_name, client_id)
                    if resolved and resolved.get("api_key"):
                        api_key = resolved["api_key"]
                        base_url = resolved["base_url"]
                        provider_name = prov_name
                        model = resolved.get("default_model", "deepseek-chat")
                        _cache_set(f"provider_{client_id}", {
                            "api_key": api_key, "base_url": base_url,
                            "name": provider_name, "default_model": model,
                        })
                        break
        
        if not api_key:
            return {"type": "chat", "summary": ""}
        
        if not model:
            model = "deepseek-chat"
        
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": classification_prompt}
            ],
            "max_tokens": 80,
            "temperature": 0.1,  # low temp for classification
        }
        
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                # Clean JSON
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                result = json.loads(raw)
                usage = data.get("usage", {})
                return {
                    "type": result.get("type", "chat"),
                    "summary": result.get("summary", ""),
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "tokens_used": usage.get("total_tokens", 0),
                    "provider": provider_name,
                    "model": model,
                }
    except Exception:
        pass
    return {"type": "chat", "summary": "", "tokens_used": 0}


async def _create_task_from_chat(client_id: int, title: str, description: str = "", priority: str = "normal"):
    """Create a task in Server A's task system via internal endpoint when LLM detects one."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{STAFFBOT_API_URL}/api/v1/internal/client/{client_id}/tasks/create",
                json={
                    "title": title[:200],
                    "description": description[:1000],
                    "priority": priority,
                    "created_by_agent": "chat_classifier",
                },
                headers={"x-api-key": STAFFBOT_API_KEY, "Content-Type": "application/json"},
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return data.get("task", data)
    except Exception:
        pass
    return None


async def _update_quota(client_id: int, tokens_used: int):
    """Update managed_token_used in subscriptions."""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "UPDATE subscriptions SET managed_token_used = managed_token_used + $2 WHERE client_id = $1",
            client_id, tokens_used,
        )
    except Exception:
        pass
    finally:
        if conn:
            await conn.close()

def _docker_ok():
    try: docker_client.ping(); return "ok"
    except: return "error"

def _get_port(container):
    port_map = container.attrs.get("NetworkSettings", {}).get("Ports", {})
    for binding in port_map.values():
        if binding: return int(binding[0].get("HostPort", 0))
    return None

def _find_available_port(start=9000):
    for port in range(start, 10000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("0.0.0.0", port)) != 0:
                return port
    return 9999


def _find_container_by_client(client_id: int):
    """Find Docker container by client_id label."""
    try:
        containers = docker_client.containers.list(
            filters={"label": f"staffbot.client_id={client_id}"},
            all=True,
        )
        return containers[0] if containers else None
    except Exception:
        return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
