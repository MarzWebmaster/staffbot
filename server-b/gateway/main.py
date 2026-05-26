#!/usr/bin/env python3
"""StaffBot.my — Server B API Gateway v2 with Chat + Tasks"""
import os, json, socket, re, httpx, asyncpg
import docker
from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

AUTH_KEY = os.environ.get("AUTH_KEY", "staffbot-secret-key")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://staffbot:staffbot@localhost:5432/staffbot_memory")
CONTAINER_DIR = "/root/staffbot/containers"
STAFFBOT_CORE_IMAGE = "staffbot-core:latest"

app = FastAPI(title="StaffBot.my — Server B Gateway", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
docker_client = docker.from_env()

# ── Pydantic Models ──────────────────────────────────────────
class DeployRequest(BaseModel):
    client_id: int; container_name: str; subdomain: str
    env_vars: dict = {}; skills: List[str] = ["chat", "memory"]
class ContainerAction(BaseModel): action: str
class ChatSend(BaseModel):
    client_id: int; container_id: Optional[int] = None
    content: str; provider: str = "openrouter"
    model: Optional[str] = None; api_key: Optional[str] = None
class TaskCreate(BaseModel):
    client_id: int; title: str; description: Optional[str] = ""
    priority: str = "normal"; assigned_to: Optional[str] = None
class TaskUpdate(BaseModel):
    status: Optional[str] = None; description: Optional[str] = None

# ── Auth ─────────────────────────────────────────────────────
async def verify_auth(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != AUTH_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ── Helpers ──────────────────────────────────────────────────
def validate_container_name(name: str) -> str:
    sanitized = re.sub(r"[^a-z0-9-]", "", name.lower().strip())
    if not sanitized or len(sanitized) < 2:
        raise HTTPException(status_code=400, detail=f"Invalid container name: {name}")
    return sanitized[:63]

def validate_skills(skills: list) -> list:
    allowed = {"chat", "memory", "tasks", "email", "gdrive", "api", "whatsapp", "telegram"}
    cleaned = [s.lower().strip() for s in (skills or ["chat", "memory"])]
    invalid = [s for s in cleaned if s not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid skills: {invalid}")
    return cleaned

async def save_message(client_id: int, role: str, content: str, container_id: int = None, model: str = None, provider: str = None, tokens: int = 0):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO chat_messages (client_id, container_id, role, content, model, provider, tokens_used) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            client_id, container_id, role, content, model, provider, tokens
        )
    finally:
        await conn.close()

async def call_llm(client_id: int, provider: str, model: str, messages: list, api_key: str = None) -> dict:
    """Call LLM provider — reads API keys from DB based on package assignment."""
    # If BYOK (user provides own key), use it directly
    if api_key:
        return await _call_provider(provider, model or "gpt-4o-mini", messages, api_key)

    # Get provider config from DB (respects package assignment)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Get client's package → available providers
        row = await conn.fetchrow("SELECT package FROM clients WHERE id=$1", client_id)
        if not row:
            return {"error": "Client not found"}
        pkg = row["package"]

        # Get first active provider assigned to this package, matching the requested provider
        # Also handles same-provider with different keys
        rows = await conn.fetch("""
            SELECT p.name, p.display_name, p.base_url, p.api_key_encrypted, p.models, p.default_model
            FROM llm_providers p
            JOIN package_providers pp ON pp.provider_id = p.id
            JOIN packages pkg ON pkg.id = pp.package_id
            WHERE pkg.name = $1 AND p.is_active = true AND pp.is_available = true
            ORDER BY p.sort_order
        """, pkg)

        if not rows:
            return {"error": f"No LLM provider available for package: {pkg}"}

        # Try the requested provider first, fallback to first available
        selected = None
        for r in rows:
            if r["name"] == provider or provider in r["name"] or r["name"] in provider:
                selected = r
                break
        if not selected:
            selected = rows[0]  # Fallback

        base_url = selected["base_url"]
        key = selected["api_key_encrypted"] or ""
        default_model = selected.get("default_model", model or "gpt-4o-mini")

        if not key:
            return {"error": f"Provider {selected['name']} has no API key configured"}

    finally:
        await conn.close()

    return await _call_provider(selected["name"], model or default_model, messages, key)


async def _call_provider(provider: str, model: str, messages: list, api_key: str) -> dict:
    """Low-level provider call."""
    configs = {
        "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions", "model": model or "gpt-4o-mini"},
        "deepseek": {"url": "https://api.deepseek.com/v1/chat/completions", "model": model or "deepseek-chat"},
        "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", "model": model or "gemini-2.0-flash"},
        "deepseek-pchp17": {"url": "https://api.deepseek.com/v1/chat/completions", "model": model or "deepseek-chat"},
        "deepseek-pchpi7": {"url": "https://api.deepseek.com/v1/chat/completions", "model": model or "deepseek-chat"},
    }
    cfg = configs.get(provider, {"url": "https://api.deepseek.com/v1/chat/completions", "model": model or "deepseek-chat"})

    headers = {"Content-Type": "application/json"}
    if "gemini" in provider:
        url = cfg["url"].format(model=cfg["model"]) + f"?key={api_key}"
        body = {"contents": [{"role": m["role"], "parts": [{"text": m["content"]}]} for m in messages]}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
        if resp.status_code != 200:
            return {"error": f"Gemini error: {resp.text}"}
        data = resp.json()
        reply = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        usage = data.get("usageMetadata", {})
        return {"reply": reply, "model": cfg["model"], "tokens": (usage.get("promptTokenCount", 0) or 0) + (usage.get("candidatesTokenCount", 0) or 0)}
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        body = {"model": cfg["model"], "messages": messages, "max_tokens": 2048}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(cfg["url"], json=body, headers=headers)
        if resp.status_code != 200:
            return {"error": f"{provider} error ({resp.status_code}): {resp.text[:200]}"}
        data = resp.json()
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        total_tokens = (usage.get("prompt_tokens", 0) or 0) + (usage.get("completion_tokens", 0) or 0)
        return {"reply": reply, "model": data.get("model", cfg["model"]), "tokens": total_tokens}

# ── Health ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    d = _docker_ok()
    return {"status": "ok", "service": "StaffBot.my Server B", "docker": d}

# ── Container Endpoints ──────────────────────────────────────
@app.post("/api/deploy")
async def deploy_container(req: DeployRequest, auth=Depends(verify_auth)):
    name = validate_container_name(req.container_name)
    req.skills = validate_skills(req.skills)
    try:
        existing = docker_client.containers.get(name)
        return {"success": True, "container_id": existing.id, "port": _get_port(existing), "message": "Already running"}
    except docker.errors.NotFound:
        pass
    os.makedirs(f"{CONTAINER_DIR}/{name}", exist_ok=True)
    port = _find_available_port()
    protected_keys = {"CLIENT_ID", "MEMORY_DB_URL", "DATABASE_URL", "AUTH_KEY", "GATEWAY_AUTH_KEY", "GATEWAY_URL", "HOSTNAME", "PATH"}
    sanitized_user_vars = {k:v for k,v in (req.env_vars or {}).items() if k not in protected_keys}
    env = {"CLIENT_ID": str(req.client_id), "SUBDOMAIN": req.subdomain,
           "GATEWAY_URL": "http://staffbot-gateway:8080", "GATEWAY_AUTH_KEY": AUTH_KEY,
           "SKILLS": ",".join(req.skills), **sanitized_user_vars}
    network_name = f"staffbot-net-{req.client_id}"
    try: docker_client.networks.get(network_name)
    except docker.errors.NotFound: docker_client.networks.create(network_name, driver="bridge", internal=False)
    try:
        container = docker_client.containers.run(
            image=STAFFBOT_CORE_IMAGE, name=name, detach=True,
            restart_policy={"Name": "unless-stopped"}, environment=env, network=network_name,
            cap_drop=["ALL"], security_opt=["no-new-privileges:true"], read_only=True,
            tmpfs={"/tmp": "size=64M"}, mem_limit="512m", memswap_limit="512m",
            cpu_quota=50000, pids_limit=100,
            ports={"8000/tcp": ("127.0.0.1", port)},
            volumes={f"{CONTAINER_DIR}/{name}": {"bind": "/app/data", "mode": "rw"}},
            labels={"staffbot.client_id": str(req.client_id), "staffbot.type": "client"},
        )
        return {"success": True, "container_id": container.id, "port": port, "container_name": name, "message": "Container deployed"}
    except docker.errors.ImageNotFound:
        return {"success": False, "port": port, "container_name": name, "message": f"Image {STAFFBOT_CORE_IMAGE} not found", "image_missing": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deploy error: {str(e)}")

@app.post("/api/container/{name}/action")
async def container_action(name: str, action: ContainerAction, auth=Depends(verify_auth)):
    try: container = docker_client.containers.get(name)
    except docker.errors.NotFound: raise HTTPException(status_code=404, detail=f"Container {name} not found")
    try:
        if action.action == "start": container.start()
        elif action.action == "stop": container.stop()
        elif action.action == "restart": container.restart()
        elif action.action == "delete": container.remove(force=True); return {"success": True, "message": f"Container {name} deleted"}
        else: raise HTTPException(status_code=400, detail=f"Unknown action: {action.action}")
        container.reload()
        return {"success": True, "status": container.status}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/container/{name}/status")
async def container_status(name: str, auth=Depends(verify_auth)):
    try:
        c = docker_client.containers.get(name)
        return {"status": c.status, "image": c.image.tags[0] if c.image.tags else "unknown", "port": _get_port(c), "created": c.attrs.get("Created", "")}
    except docker.errors.NotFound: return {"status": "not_found"}

@app.get("/api/containers")
async def list_containers(auth=Depends(verify_auth)):
    containers = docker_client.containers.list(filters={"label": "staffbot.type=client"}, all=True)
    return [{"id": c.id[:12], "name": c.name, "status": c.status, "client_id": c.labels.get("staffbot.client_id", ""), "port": _get_port(c)} for c in containers]

@app.put("/api/container/{name}")
async def update_container(name: str, data: dict, auth=Depends(verify_auth)):
    return {"success": True, "message": "Env vars recorded. Restart container to apply."}

@app.post("/api/notify/whatsapp")
async def send_whatsapp(data: dict, auth=Depends(verify_auth)):
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post("http://localhost:8653/send-message", json={"to": data.get("to"), "message": data.get("message")}, timeout=15.0)
            return resp.json()
        except Exception as e: return {"success": False, "error": f"Baileys error: {str(e)}"}

# ── Memory Endpoints ─────────────────────────────────────────
@app.post("/api/memory/search")
async def search_memory(client_id: int = Query(...), query: str = Query(...), limit: int = 5, auth=Depends(verify_auth)):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("SELECT content, metadata, created_at FROM client_memory WHERE client_id=$1 ORDER BY created_at DESC LIMIT $2", client_id, limit)
        return [dict(r) for r in rows]
    finally: await conn.close()

@app.post("/api/memory/save")
async def save_memory(client_id: int, content: str, metadata: dict = {}, auth=Depends(verify_auth)):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("INSERT INTO client_memory (client_id, content, metadata) VALUES ($1, $2, $3)", client_id, content, json.dumps(metadata))
        return {"success": True}
    finally: await conn.close()
# ── NEW: Chat Endpoints ──────────────────────────────────────
async def get_governance_policy(client_id: int) -> dict:
    """Get governance policy + package limits for a client."""
    policy_block = ""
    allowed_skills = []
    allowed_tools = []
    package_info = {}

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # 1. Get client's package
        client_row = await conn.fetchrow(
            "SELECT package FROM clients WHERE id=$1", client_id
        )
        if not client_row:
            return {"system_prompt": "", "package": {}}

        package_name = client_row["package"]

        # 2. Get ALL package settings
        pkg_row = await conn.fetchrow(
            "SELECT name, display_name, features, bot_limit, sub_ejen_limit, "
            "managed_tokens, allow_byok, cpu_limit, memory_limit_mb, storage_limit_gb, "
            "skill_category_ids, tool_category_ids "
            "FROM packages WHERE name=$1 AND is_active=true",
            package_name
        )
        if not pkg_row:
            return {"system_prompt": "", "package": {}}

        # Package limits
        package_info = {
            "name": pkg_row["name"],
            "display_name": pkg_row["display_name"],
            "features": json.loads(pkg_row["features"]) if isinstance(pkg_row["features"], str) else (pkg_row["features"] or []),
            "bot_limit": pkg_row["bot_limit"] or 1,
            "sub_ejen_limit": pkg_row["sub_ejen_limit"] or 3,
            "managed_tokens": pkg_row["managed_tokens"] or 5000000,
            "allow_byok": pkg_row["allow_byok"] or False,
            "cpu_limit": float(pkg_row["cpu_limit"] or 0.5),
            "memory_limit_mb": pkg_row["memory_limit_mb"] or 512,
            "storage_limit_gb": pkg_row["storage_limit_gb"] or 1,
        }

        skill_cat_ids = pkg_row["skill_category_ids"] or []
        tool_cat_ids = pkg_row["tool_category_ids"] or []

        # 3. Get skill category names
        if skill_cat_ids:
            cats = await conn.fetch(
                "SELECT name FROM skill_categories WHERE id = ANY($1::int[])", skill_cat_ids
            )
            allowed_skill_cats = {r["name"] for r in cats}
        else:
            allowed_skill_cats = set()

        # 4. Get tool category names
        if tool_cat_ids:
            cats = await conn.fetch(
                "SELECT name FROM tool_categories WHERE id = ANY($1::int[])", tool_cat_ids
            )
            allowed_tool_cats = {r["name"] for r in cats}
        else:
            allowed_tool_cats = set()

        # 5. Get governance policy
        setting_row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key=$1", "governance_policy"
        )
        if setting_row:
            policy_data = json.loads(setting_row["value"])
            enabled_skills = policy_data.get("enabled_skills", [])
            enabled_tools = policy_data.get("enabled_tools", [])
            skill_categories_map = policy_data.get("skill_categories", {})
            restrictions = policy_data.get("general_restrictions", [])
            policy_text = policy_data.get("policy_text", "")

            # 2-layer filter: governance_policy enabled ∩ package allowed categories
            if allowed_skill_cats and skill_categories_map:
                allowed_skills = [s for s in enabled_skills if skill_categories_map.get(s, "unknown") in allowed_skill_cats]
            else:
                allowed_skills = enabled_skills

            allowed_tools = enabled_tools

            # Build system prompt block
            policy_block = "\n## Governance Policy — StaffBot.my\n"
            policy_block += "The following policy governs ALL your responses. You MUST comply.\n\n"

            # Package info
            policy_block += "### Your Package\n"
            policy_block += f"Package: **{package_info['display_name']}**\n"
            policy_block += f"Bot Limit: {package_info['bot_limit']} | Sub Ejen: {package_info['sub_ejen_limit']} | Tokens: {package_info['managed_tokens']:,}/month\n"
            if package_info["features"]:
                policy_block += "Features: " + ", ".join(package_info["features"]) + "\n"
            policy_block += "\n"

            if allowed_skills:
                policy_block += f"### Enabled Skills ({len(allowed_skills)})\n"
                policy_block += "You may ONLY use skills from this list:\n"
                for s in allowed_skills:
                    policy_block += f"- `{s}`\n"
                policy_block += "\n"

            if allowed_tools:
                policy_block += f"### Enabled Tools ({len(allowed_tools)})\n"
                policy_block += "You may ONLY use tools from this list:\n"
                for t in allowed_tools:
                    policy_block += f"- `{t}`\n"
                policy_block += "\n"

            if restrictions:
                policy_block += "### General Restrictions\n"
                for r in restrictions:
                    policy_block += f"- ⛔ {r}\n"
                policy_block += "\n"

            if policy_text:
                policy_block += "### Full Policy\n"
                policy_block += policy_text[:2000]
                policy_block += "\n"

    except Exception as e:
        policy_block = ""
    finally:
        await conn.close()

    return {
        "system_prompt": policy_block,
        "allowed_skills": allowed_skills,
        "allowed_tools": allowed_tools,
        "package": package_info,
    }


@app.post("/api/chat/send")
async def chat_send(data: ChatSend, auth=Depends(verify_auth)):
    """Send a chat message and get AI response."""
    # Save user message
    await save_message(data.client_id, "user", data.content, data.container_id, data.model, data.provider)

    # Get recent conversation history (last 10 messages)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT role, content FROM chat_messages WHERE client_id=$1 ORDER BY created_at DESC LIMIT 10",
            data.client_id
        )
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    finally:
        await conn.close()

    # Fetch governance policy + package limits
    gov = await get_governance_policy(data.client_id)
    gov_prompt = gov.get("system_prompt", "")
    pkg = gov.get("package", {})

    # BYOK check: reject custom API keys if package doesn't allow
    if data.api_key and not pkg.get("allow_byok", False):
        await save_message(data.client_id, "assistant",
            "BYOK not available on your package. Upgrade to Enterprise for custom API keys.",
            data.container_id, data.model, data.provider)
        return {"success": False, "error": "BYOK not available on your plan. Upgrade to Enterprise."}

    if not history:
        base_prompt = "You are StaffBot.my — a helpful Digital Employee AI assistant."
        if gov_prompt:
            base_prompt += "\n\n" + gov_prompt
        history = [{"role": "system", "content": base_prompt}]
    elif gov_prompt:
        # Prepend governance policy to the first system message or add as new system message
        if history[0]["role"] == "system":
            history[0]["content"] = history[0]["content"] + "\n\n" + gov_prompt
        else:
            history.insert(0, {"role": "system", "content": "You are StaffBot.my — a helpful Digital Employee AI assistant.\n\n" + gov_prompt})

    # Call LLM
    result = await call_llm(data.client_id, data.provider, data.model, history, data.api_key)

    if "error" in result:
        await save_message(data.client_id, "assistant", "\u26a0\ufe0f " + result.get("error", "Unknown error"), data.container_id, data.model, data.provider)
        return {"success": False, "error": result["error"]}

    tokens_used = result.get("tokens", 0)

    # Token accounting: BYOK = no deduction, managed = deduct
    is_byok = bool(data.api_key)
    if not is_byok and tokens_used > 0:
        # Log token usage for quota tracking
        try:
            conn2 = await asyncpg.connect(DATABASE_URL)
            await conn2.execute(
                "INSERT INTO token_usage_log (client_id, tokens_used, provider, model, is_byok) VALUES ($1,$2,$3,$4,$5)",
                data.client_id, tokens_used, data.provider, result.get("model", ""), False
            )
            await conn2.close()
        except Exception:
            pass  # Non-critical

    # Save assistant response
    await save_message(data.client_id, "assistant", result["reply"], data.container_id, result.get("model"), data.provider, tokens_used)

    return {
        "success": True,
        "reply": result["reply"],
        "model": result.get("model"),
        "tokens_used": tokens_used,
        "byok": is_byok,
        "package": pkg.get("display_name", ""),
    }

@app.get("/api/chat/history")
async def chat_history(client_id: int = Query(...), container_id: int = None, limit: int = 50, before_id: int = None, auth=Depends(verify_auth)):
    """Get chat message history."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if container_id:
            if before_id:
                rows = await conn.fetch(
                    "SELECT id, role, content, model, provider, tokens_used, created_at FROM chat_messages WHERE client_id=$1 AND container_id=$2 AND id<$3 ORDER BY created_at DESC LIMIT $4",
                    client_id, container_id, before_id, limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, role, content, model, provider, tokens_used, created_at FROM chat_messages WHERE client_id=$1 AND container_id=$2 ORDER BY created_at DESC LIMIT $3",
                    client_id, container_id, limit
                )
        else:
            if before_id:
                rows = await conn.fetch(
                    "SELECT id, role, content, model, provider, tokens_used, created_at FROM chat_messages WHERE client_id=$1 AND id<$2 ORDER BY created_at DESC LIMIT $3",
                    client_id, before_id, limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, role, content, model, provider, tokens_used, created_at FROM chat_messages WHERE client_id=$1 ORDER BY created_at DESC LIMIT $2",
                    client_id, limit
                )
        messages = [dict(r) for r in rows]
        for m in messages:
            m["created_at"] = m["created_at"].isoformat() if m["created_at"] else None
        return {"messages": messages, "total": len(messages)}
    finally: await conn.close()

# ── NEW: Task Endpoints ──────────────────────────────────────
@app.post("/api/tasks/create")
async def task_create(data: TaskCreate, auth=Depends(verify_auth)):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "INSERT INTO tasks (client_id, title, description, priority, assigned_to) VALUES ($1,$2,$3,$4,$5) RETURNING *",
            data.client_id, data.title, data.description, data.priority, data.assigned_to
        )
        return dict(row)
    finally: await conn.close()

@app.get("/api/tasks/list")
async def task_list(client_id: int = Query(...), status: str = None, auth=Depends(verify_auth)):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if status:
            rows = await conn.fetch("SELECT * FROM tasks WHERE client_id=$1 AND status=$2 ORDER BY created_at DESC", client_id, status)
        else:
            rows = await conn.fetch("SELECT * FROM tasks WHERE client_id=$1 ORDER BY created_at DESC", client_id)
        return [dict(r) for r in rows]
    finally: await conn.close()

@app.put("/api/tasks/{task_id}")
async def task_update(task_id: int, data: TaskUpdate, auth=Depends(verify_auth)):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        updates = []
        params = []
        i = 1
        if data.status:
            updates.append(f"status=${i}"); params.append(data.status); i+=1
            if data.status == "completed":
                updates.append(f"completed_at=NOW()")
        if data.description is not None:
            updates.append(f"description=${i}"); params.append(data.description); i+=1
        updates.append(f"updated_at=NOW()")
        params.append(task_id)
        row = await conn.fetchrow("UPDATE tasks SET " + ",".join(updates) + " WHERE id=" + str(i) + " RETURNING *", *params)
        return dict(row) if row else {"error": "Task not found"}
    finally: await conn.close()

# ── Internal ─────────────────────────────────────────────────
def _docker_ok():
    try: docker_client.ping(); return "ok"
    except: return "error"
def _get_port(container):
    pm = container.attrs.get("NetworkSettings", {}).get("Ports", {})
    for b in pm.values():
        if b: return int(b[0].get("HostPort", 0))
    return None
def _find_available_port(start=9000):
    for port in range(start, 10000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("0.0.0.0", port)) != 0: return port
    return 9999

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
