#!/usr/bin/env python3
"""
StaffBot.my — Hermes Gateway API v2.2
=====================================
Direct LLM calls via httpx — no subprocess overhead.
Provider config via env vars (MIMO_API_KEY, MIMO_BASE_URL).
v2.2: Tool/function calling support for task management.
"""

import asyncio, json, os, sys, time, yaml
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

# ── Tool Definitions ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task for the user. Use when user asks to create, add, or make a task/todo/reminder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title (required)"},
                    "description": {"type": "string", "description": "Task description (optional)"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Task priority"},
                    "assigned_to": {"type": "string", "description": "Agent name to assign to (optional). If user says 'assign to Sarah', put 'Sarah' here."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks for the user. Use when user asks to see, show, or list their tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"], "description": "Filter by status"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Filter by priority"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update a task's status, priority, or assignment. Use when user asks to mark task as done, complete, or change status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Task ID to update"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"], "description": "New status"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "New priority"},
                    "assigned_to": {"type": "string", "description": "Reassign to agent name"},
                },
                "required": ["task_id"],
            },
        },
    },
]

# ── Tool Execution ────────────────────────────────────────────────

async def execute_tool(tool_name: str, arguments: dict, client_id: int, token: str = "") -> str:
    """Execute a tool call by hitting the StaffBot API."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            if tool_name == "create_task":
                arguments["created_by_agent"] = "AI Assistant"
                r = await cl.post(
                    f"{API_BASE}/api/v1/tasks/create",
                    json=arguments,
                    headers=headers,
                )
                if r.status_code == 200:
                    task = r.json()
                    return json.dumps({"success": True, "task_id": task["id"], "title": task["title"], "status": task["status"]})
                return json.dumps({"success": False, "error": r.text[:200]})

            elif tool_name == "list_tasks":
                params = {k: v for k, v in arguments.items() if v}
                r = await cl.get(
                    f"{API_BASE}/api/v1/tasks/list",
                    params=params,
                    headers=headers,
                )
                if r.status_code == 200:
                    tasks = r.json()
                    return json.dumps({"success": True, "tasks": tasks, "count": len(tasks)})
                return json.dumps({"success": False, "error": r.text[:200]})

            elif tool_name == "update_task":
                task_id = arguments.pop("task_id")
                r = await cl.put(
                    f"{API_BASE}/api/v1/tasks/{task_id}",
                    json=arguments,
                    headers=headers,
                )
                if r.status_code == 200:
                    task = r.json()
                    return json.dumps({"success": True, "task_id": task["id"], "status": task["status"]})
                return json.dumps({"success": False, "error": r.text[:200]})

            else:
                return json.dumps({"success": False, "error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)[:200]})


# ── App Setup ─────────────────────────────────────────────────────

app = FastAPI(title="StaffBot.my Gateway v2.2")
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
    auth_token: Optional[str] = None  # For tool API calls


class ReloadProfileRequest(BaseModel):
    client_id: int
    package: Optional[str] = None


async def verify_auth(x_api_key: str = Header(None, alias="x-api-key")):
    if x_api_key != GATEWAY_AUTH:
        raise HTTPException(status_code=401)


@app.get("/health")
async def health():
    return {"status": "ok", "gateway": "hermes", "version": "2.2.0"}


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
            _call_llm(cid, req.content, req.provider, req.model, req.api_key, req.system_context, req.auth_token, req.container_id)
        )
        await security.audit(cid, "chat", "success")
        return result
    except TimeoutError:
        return {"success": False, "error": "timeout"}


async def _call_llm(client_id, content, provider="mimo", model=None, api_key=None, system_ctx=None, auth_token=None, container_id=None):
    cfg = PROVIDERS.get(provider, PROVIDERS["mimo"])
    key = api_key or cfg["api_key"]
    model = model or cfg["default_model"]

    soul = _load_soul(client_id, container_id)
    messages = []
    if soul:
        messages.append({"role": "system", "content": soul[:3000]})
    if system_ctx:
        messages.append({"role": "system", "content": system_ctx})
    messages.append({"role": "user", "content": content})

    total_input = 0
    total_output = 0

    try:
        # Tool-calling loop (max 3 rounds)
        for round_num in range(3):
            async with httpx.AsyncClient(timeout=120) as cl:
                r = await cl.post(
                    cfg["base_url"] + "/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": 2048,
                        "temperature": 0.7,
                        "stream": False,
                        "tools": TOOL_DEFINITIONS,
                        "tool_choice": "auto",
                    },
                    headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + key} if key else {})},
                )
            if r.status_code != 200:
                return {"success": False, "error": f"LLM {r.status_code}", "message": r.text[:300]}

            data = r.json()
            usage = data.get("usage", {})
            total_input += usage.get("prompt_tokens", 0)
            total_output += usage.get("completion_tokens", 0)

            choice = data["choices"][0]
            msg = choice["message"]

            # Check if LLM wants to call tools
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # Add assistant message with tool calls to history
                messages.append(msg)

                # Execute each tool call
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        fn_args = {}

                    tool_result = await execute_tool(fn_name, fn_args, client_id, auth_token or "")

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })

                # Continue loop — LLM will generate final response
                continue

            # No tool calls — return the text response
            reply = msg.get("content", "")
            await rate_limiter.record(client_id, total_input + total_output)

            return {
                "success": True,
                "content": reply,
                "model": model,
                "provider": provider,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "tokens_used": total_input + total_output,
                "tool_rounds": round_num,
            }

        # Max rounds reached
        return {
            "success": True,
            "content": messages[-1].get("content", "Task processed.") if messages else "Task processed.",
            "model": model,
            "provider": provider,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "tokens_used": total_input + total_output,
        }

    except httpx.TimeoutException:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": "llm_error", "message": str(e)[:200]}


def _load_soul(client_id, container_id=None):
    # Try container-specific SOUL first
    if container_id:
        path = os.path.join(PROFILES_DIR, f"client_{client_id}", f"container_{container_id}", "SOUL.md")
        if os.path.exists(path):
            with open(path) as f:
                return f.read()[:3000]

    # Fallback to client SOUL
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
