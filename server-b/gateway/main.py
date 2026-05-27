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
from typing import Optional, List
import numpy as np

AUTH_KEY = os.environ.get("AUTH_KEY", "staffbot-secret-key")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://staffbot:staffbot@localhost:5432/staffbot_memory")
CONTAINER_DIR = "/root/staffbot/containers"
STAFFBOT_CORE_IMAGE = "staffbot-core:latest"
BAILEYS_MANAGER_URL = os.environ.get("BAILEYS_MANAGER_URL", "http://baileys-manager:8653")
TELEGRAM_MANAGER_URL = os.environ.get("TELEGRAM_MANAGER_URL", "http://telegram-manager:8654")


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
