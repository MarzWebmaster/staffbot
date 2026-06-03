#!/usr/bin/env python3
"""
StaffBot.my — Hermes Gateway API v2.3
=====================================
v2.3: Vision support — auto-switch to Omni for images + multimodal content
"""

import asyncio, json, os, sys, time, yaml, re
from typing import Optional, List
import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/opt/staffbot/scripts")
from rate_limiter import RateLimiter
from request_queue import RequestQueue
from security import SecurityMiddleware

GATEWAY_AUTH = os.environ.get("GATEWAY_AUTH", "gw-staffbot-secure-key-2026")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
PROFILES_DIR = os.environ.get("STAFFBOT_PROFILES_DIR", "/app/data/profiles")
API_BASE = os.environ.get("API_BASE_URL", "http://staffbot-api:8000")

MIMO_KEY = os.environ.get("MIMO_API_KEY", "")
MIMO_BASE = os.environ.get("MIMO_BASE_URL", "https://jemaahapi.tail5cfbb9.ts.net/v1")

# ── Model Registry ───────────────────────────────────────────────

MODEL_REGISTRY = {
    "mimo/mimo-v2.5-pro":    {"context": 1_048_576, "vision": False, "max_output": 131_072, "desc": "Best for long docs & reasoning"},
    "mimo/mimo-v2.5":        {"context": 1_048_576, "vision": False, "max_output": 131_072, "desc": "General purpose"},
    "mimo/mimo-v2-omni":     {"context": 1_048_576, "vision": True,  "max_output": 131_072, "desc": "Multimodal — sees images"},
    "mimo/mimo-v2-flash":    {"context": 1_048_576, "vision": False, "max_output": 131_072, "desc": "Fastest"},
    "deepseek-chat":         {"context": 65_536,     "vision": False, "max_output": 8_192,   "desc": "Budget text model"},
    "deepseek-reasoner":     {"context": 65_536,     "vision": False, "max_output": 8_192,   "desc": "Deep reasoning"},
}

PROVIDERS = {
    "mimo": {
        "base_url": MIMO_BASE,
        "api_key": MIMO_KEY,
        "models": list(MODEL_REGISTRY.keys()),
        "default_model": "mimo/mimo-v2.5",
        "vision_model": "mimo/mimo-v2-omni",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "vision_model": None,  # DeepSeek no vision
    },
}

# ── Image Detection ──────────────────────────────────────────────

def _has_image(content: str) -> bool:
    """Detect if content contains image data (base64 or IMAGE marker)."""
    return bool(re.search(r'\[IMAGE\b|image_base64|data:image/', content))

def _extract_images(content: str) -> List[dict]:
    """Extract base64 images from content. Returns list of {mime_type, data}."""
    images = []
    # Match [IMAGE N: filename]
    # Look for data:image/... patterns in the content
    for m in re.finditer(r'data:image/(\w+);base64,([A-Za-z0-9+/=]+)', content):
        images.append({"mime_type": f"image/{m.group(1)}", "data": m.group(2)})
    return images

def _build_multimodal_content(text: str, images: List[dict]) -> list:
    """Build OpenAI-compatible multimodal content array."""
    parts = [{"type": "text", "text": text}]
    for img in images:
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img['mime_type']};base64,{img['data']}"}
        })
    return parts

def _strip_image_data(text: str) -> str:
    """Remove base64 image data from text to keep prompt clean."""
    return re.sub(r'data:image/\w+;base64,[A-Za-z0-9+/=]+', '[IMAGE ATTACHED]', text)

# ── Tool Definitions ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task. Use when user asks to create/add/make a task/todo/reminder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Task description"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "assigned_to": {"type": "string", "description": "Agent name to assign to"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks. Use when user asks to see/show/list tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update task status/priority/assignment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "assigned_to": {"type": "string"},
                },
                "required": ["task_id"],
            },
        },
    },
]

# ── Tool Execution ────────────────────────────────────────────────

async def execute_tool(tool_name: str, arguments: dict, client_id: int, token: str = "") -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            if tool_name == "create_task":
                arguments["created_by_agent"] = "AI Staff"
                r = await cl.post(f"{API_BASE}/api/v1/tasks/create", json=arguments, headers=headers)
                task = r.json() if r.status_code == 200 else {"success": False, "error": r.text[:200]}
                return json.dumps(task)
            elif tool_name == "list_tasks":
                params = {k: v for k, v in arguments.items() if v}
                r = await cl.get(f"{API_BASE}/api/v1/tasks/list", params=params, headers=headers)
                tasks = r.json() if r.status_code == 200 else []
                return json.dumps({"success": True, "tasks": tasks, "count": len(tasks)})
            elif tool_name == "update_task":
                tid = arguments.pop("task_id")
                r = await cl.put(f"{API_BASE}/api/v1/tasks/{tid}", json=arguments, headers=headers)
                return json.dumps(r.json() if r.status_code == 200 else {"success": False, "error": r.text[:200]})
            return json.dumps({"success": False, "error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)[:200]})

# ── App Setup ─────────────────────────────────────────────────────

app = FastAPI(title="StaffBot.my Gateway v2.3")
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
    auth_token: Optional[str] = None
    image_base64: Optional[str] = None

class ReloadProfileRequest(BaseModel):
    client_id: int
    package: Optional[str] = None

async def verify_auth(x_api_key: str = Header(None, alias="x-api-key")):
    if x_api_key != GATEWAY_AUTH:
        raise HTTPException(status_code=401)

@app.get("/health")
async def health():
    return {"status": "ok", "gateway": "hermes", "version": "2.3.0"}

@app.post("/api/chat/send")
async def chat_send(req: ChatRequest):
    cid = req.client_id
    await security.enforce_all(cid, "llm_call", content=req.content)
    if not await rate_limiter.check(cid):
        return {"success": False, "error": "rate_limited"}
    if await rate_limiter.is_exhausted(cid):
        return {"success": False, "error": "token_quota_exceeded"}
    try:
        result = await request_queue.enqueue(cid, _call_llm(cid, req))
        await security.audit(cid, "chat", "success")
        return result
    except TimeoutError:
        return {"success": False, "error": "timeout"}

async def _call_llm(client_id: int, req: ChatRequest):
    provider = req.provider or "mimo"
    cfg = PROVIDERS.get(provider, PROVIDERS["mimo"])
    key = req.api_key or cfg["api_key"]
    model = req.model or cfg["default_model"]
    content = req.content

    # ── Vision Detection ─────────────────────────────────────────
    images = _extract_images(content)
    has_image = bool(images) or _has_image(content)

    if has_image:
        vision_model = cfg.get("vision_model")
        if vision_model and vision_model != model:
            model = vision_model
            print(f"[Vision] Auto-switched to {model} for image analysis")
        elif not vision_model:
            print(f"[Vision] Provider {provider} has no vision model — image skipped")

    # Clean content
    clean_content = _strip_image_data(content)

    # ── Build Messages ───────────────────────────────────────────
    soul = _load_soul(client_id, req.container_id)
    messages = []
    if soul:
        messages.append({"role": "system", "content": soul[:3000]})
    if req.system_context:
        messages.append({"role": "system", "content": req.system_context})

    if has_image and images:
        # Multimodal format
        user_content = _build_multimodal_content(clean_content, images)
    else:
        user_content = clean_content

    messages.append({"role": "user", "content": user_content})

    total_input = total_output = 0
    actual_model = model

    try:
        for round_num in range(3):
            async with httpx.AsyncClient(timeout=120) as cl:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 8192,
                    "temperature": 0.7,
                    "stream": False,
                }
                if not has_image:
                    payload["tools"] = TOOL_DEFINITIONS
                    payload["tool_choice"] = "auto"

                r = await cl.post(
                    cfg["base_url"] + "/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + key} if key else {})},
                )

            if r.status_code != 200:
                return {"success": False, "error": f"LLM {r.status_code}", "message": r.text[:300]}

            data = r.json()
            usage = data.get("usage", {})
            total_input += usage.get("prompt_tokens", 0)
            total_output += usage.get("completion_tokens", 0)
            actual_model = data.get("model", model)

            choice = data["choices"][0]
            msg = choice["message"]

            tool_calls = msg.get("tool_calls")
            if tool_calls and not has_image:
                messages.append(msg)
                for tc in tool_calls:
                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        fn_args = {}
                    tool_result = await execute_tool(tc["function"]["name"], fn_args, client_id, req.auth_token or "")
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
                continue

            reply = msg.get("content", "")
            await rate_limiter.record(client_id, total_input + total_output)

            return {
                "success": True, "content": reply, "model": actual_model,
                "provider": provider, "input_tokens": total_input,
                "output_tokens": total_output, "tokens_used": total_input + total_output,
                "vision_used": has_image, "tool_rounds": round_num,
            }

        return {"success": True, "content": messages[-1].get("content", "Task processed.") if messages else "Task processed.",
                "model": actual_model, "provider": provider,
                "input_tokens": total_input, "output_tokens": total_output,
                "tokens_used": total_input + total_output}

    except httpx.TimeoutException:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": "llm_error", "message": str(e)[:200]}

def _load_soul(client_id, container_id=None):
    if container_id:
        path = os.path.join(PROFILES_DIR, f"client_{client_id}", f"container_{container_id}", "SOUL.md")
        if os.path.exists(path):
            with open(path) as f:
                return f.read()[:3000]
    path = os.path.join(PROFILES_DIR, f"client_{client_id}", "SOUL.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()[:3000]
    return ""

@app.get("/api/chat/history")
async def chat_history(client_id: int, limit: int = 10):
    return {"client_id": client_id, "messages": []}

@app.get("/api/v1/admin/stats")
async def admin_stats():
    return {"profiles": len([d for d in os.listdir(PROFILES_DIR) if d.startswith("client_")])}

@app.post("/admin/reload-profile")
async def reload_profile(req: ReloadProfileRequest):
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
    return {"success": True, "client_id": cid, "package": package, "limits": stats}


@app.post("/admin/regenerate-config")
async def regenerate_config(config: dict, x_api_key: str = Header(None, alias="x-api-key")):
    """Receive config from API and apply it + reload Hermes."""
    if x_api_key != GATEWAY_AUTH:
        raise HTTPException(status_code=401)
    import os as _os, signal as _signal
    try:
        _os.makedirs(_os.path.dirname("/app/data/config.yaml") or ".", exist_ok=True)
        with open("/app/data/config.yaml", "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        # SIGHUP Hermes server
        for pid in _os.listdir("/proc"):
            if pid.isdigit():
                try:
                    with open(f"/proc/{pid}/cmdline") as pf:
                        cmd = pf.read()
                    if "hermes" in cmd and "server" in cmd:
                        _os.kill(int(pid), _signal.SIGHUP)
                        break
                except:
                    pass
        return {"success": True, "message": "Config applied and Hermes reloaded"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

@app.put("/admin/reload-profile/batch")
async def reload_profiles_batch(client_ids: list[int]):
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
