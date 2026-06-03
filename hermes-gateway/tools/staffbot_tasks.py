#!/usr/bin/env python3
"""
StaffBot Tasks Tool — Hermes Native Tool

Provides task management via StaffBot API.
Tools: create_task, list_tasks, update_task, delete_task, task_stats

All tools call the StaffBot API internally with GATEWAY_API_KEY for auth.
Client context (client_id) is passed from the LLM via tool arguments.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List


STAFFBOT_API_BASE = os.getenv("STAFFBOT_API_BASE", "http://staffbot-api:8000/api/v1")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")


def _api_request(method: str, path: str, client_id: int, body: Optional[Dict] = None) -> Dict[str, Any]:
    """Make an authenticated request to the StaffBot API."""
    url = f"{STAFFBOT_API_BASE}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Key": GATEWAY_API_KEY,
        "X-Client-ID": str(client_id),
    }
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"success": True, "data": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return {"success": False, "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool Handlers ──────────────────────────────────────────────────────

def create_task_handler(
    client_id: int,
    title: str,
    description: str = "",
    priority: str = "medium",
    assigned_to: str = "",
    container_id: Optional[int] = None,
) -> str:
    """Create a new task for the client."""
    body = {
        "title": title,
        "description": description,
        "priority": priority,
        "assigned_to": assigned_to,
    }
    if container_id:
        body["container_id"] = container_id

    result = _api_request("POST", "/tasks/create", client_id, body)
    return json.dumps(result, ensure_ascii=False)


def list_tasks_handler(
    client_id: int,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> str:
    """List tasks for the client with optional filters."""
    params = []
    if status:
        params.append(f"status={status}")
    if priority:
        params.append(f"priority={priority}")
    if assigned_to:
        params.append(f"assigned_to={assigned_to}")

    path = "/tasks/list"
    if params:
        path += "?" + "&".join(params)

    result = _api_request("GET", path, client_id)
    return json.dumps(result, ensure_ascii=False)


def update_task_handler(
    client_id: int,
    task_id: int,
    status: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> str:
    """Update an existing task."""
    body = {}
    if status:
        body["status"] = status
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if priority:
        body["priority"] = priority
    if assigned_to:
        body["assigned_to"] = assigned_to

    result = _api_request("PUT", f"/tasks/{task_id}", client_id, body)
    return json.dumps(result, ensure_ascii=False)


def delete_task_handler(client_id: int, task_id: int) -> str:
    """Delete a task."""
    result = _api_request("DELETE", f"/tasks/{task_id}", client_id)
    return json.dumps(result, ensure_ascii=False)


def task_stats_handler(client_id: int) -> str:
    """Get task statistics (counts by status/priority)."""
    result = _api_request("GET", "/tasks/stats/summary", client_id)
    return json.dumps(result, ensure_ascii=False)


# ── Requirement Check ──────────────────────────────────────────────────

def check_staffbot_tasks_requirements() -> bool:
    """Check that StaffBot API is reachable and gateway key is set."""
    return bool(GATEWAY_API_KEY)


# ── OpenAI Function-Calling Schemas ────────────────────────────────────

CREATE_TASK_SCHEMA = {
    "name": "create_task",
    "description": (
        "Create a new task for the current client. Tasks appear on the Tasks page. "
        "Use this when the user asks to create a task, set a reminder, or assign work. "
        "Agents can create tasks for themselves or for other agents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            },
            "title": {
                "type": "string",
                "description": "Task title — short and clear."
            },
            "description": {
                "type": "string",
                "description": "Detailed task description."
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Task priority level.",
                "default": "medium"
            },
            "assigned_to": {
                "type": "string",
                "description": "Who the task is assigned to — agent name or 'me'."
            },
            "container_id": {
                "type": "integer",
                "description": "Container/agent ID if assigning to a specific AI staff."
            }
        },
        "required": ["client_id", "title"]
    }
}

LIST_TASKS_SCHEMA = {
    "name": "list_tasks",
    "description": (
        "List all tasks for the current client. Use optional filters for status/priority. "
        "Use this when the user asks 'what are my tasks?' or 'show me pending tasks'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled"],
                "description": "Filter by task status."
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Filter by priority."
            },
            "assigned_to": {
                "type": "string",
                "description": "Filter by assigned agent."
            }
        },
        "required": ["client_id"]
    }
}

UPDATE_TASK_SCHEMA = {
    "name": "update_task",
    "description": (
        "Update an existing task — change its status, title, description, priority, or assignment. "
        "Use this when the user says 'mark task as done', 'change priority', or 'reassign task'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            },
            "task_id": {
                "type": "integer",
                "description": "The ID of the task to update."
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled"],
                "description": "New status for the task."
            },
            "title": {
                "type": "string",
                "description": "New title."
            },
            "description": {
                "type": "string",
                "description": "New description."
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "New priority."
            },
            "assigned_to": {
                "type": "string",
                "description": "Reassign to a different agent."
            }
        },
        "required": ["client_id", "task_id"]
    }
}

DELETE_TASK_SCHEMA = {
    "name": "delete_task",
    "description": (
        "Delete a task permanently. "
        "Use cautiously — only when the user explicitly asks to delete/remove a task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            },
            "task_id": {
                "type": "integer",
                "description": "The ID of the task to delete."
            }
        },
        "required": ["client_id", "task_id"]
    }
}

TASK_STATS_SCHEMA = {
    "name": "task_stats",
    "description": (
        "Get task statistics for the current client — counts by status and priority. "
        "Useful for dashboards and summaries."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            }
        },
        "required": ["client_id"]
    }
}


# ── Registry ───────────────────────────────────────────────────────────

from tools.registry import registry, tool_error

registry.register(
    name="create_task",
    toolset="staffbot",
    schema=CREATE_TASK_SCHEMA,
    handler=lambda args, **kw: create_task_handler(
        client_id=args.get("client_id"),
        title=args["title"],
        description=args.get("description", ""),
        priority=args.get("priority", "medium"),
        assigned_to=args.get("assigned_to", ""),
        container_id=args.get("container_id"),
    ),
    check_fn=check_staffbot_tasks_requirements,
    emoji="📝",
)

registry.register(
    name="list_tasks",
    toolset="staffbot",
    schema=LIST_TASKS_SCHEMA,
    handler=lambda args, **kw: list_tasks_handler(
        client_id=args["client_id"],
        status=args.get("status"),
        priority=args.get("priority"),
        assigned_to=args.get("assigned_to"),
    ),
    check_fn=check_staffbot_tasks_requirements,
    emoji="📋",
)

registry.register(
    name="update_task",
    toolset="staffbot",
    schema=UPDATE_TASK_SCHEMA,
    handler=lambda args, **kw: update_task_handler(
        client_id=args["client_id"],
        task_id=args["task_id"],
        status=args.get("status"),
        title=args.get("title"),
        description=args.get("description"),
        priority=args.get("priority"),
        assigned_to=args.get("assigned_to"),
    ),
    check_fn=check_staffbot_tasks_requirements,
    emoji="✏️",
)

registry.register(
    name="delete_task",
    toolset="staffbot",
    schema=DELETE_TASK_SCHEMA,
    handler=lambda args, **kw: delete_task_handler(
        client_id=args["client_id"],
        task_id=args["task_id"],
    ),
    check_fn=check_staffbot_tasks_requirements,
    emoji="🗑️",
)

registry.register(
    name="task_stats",
    toolset="staffbot",
    schema=TASK_STATS_SCHEMA,
    handler=lambda args, **kw: task_stats_handler(
        client_id=args["client_id"],
    ),
    check_fn=check_staffbot_tasks_requirements,
    emoji="📊",
)
