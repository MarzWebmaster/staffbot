"""StaffBot.my core tools for Hermes.

A thin client: each tool calls the StaffBot platform (/api/v1/agent-tools)
with this customer's token. Webhook credentials and SMTP passwords stay on the
platform; the platform also enforces rate limits and blocks internal addresses.

Env (from the managed /etc/hermes/.env):
  STAFFBOT_API_URL      e.g. http://172.30.0.1:8000
  STAFFBOT_LLM_TOKEN    the customer's sbk_ token
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TOOLSET = "staffbot"
TIMEOUT = 60


def _call(method, path, payload=None, query=None):
    base = os.environ.get("STAFFBOT_API_URL", "").rstrip("/")
    token = os.environ.get("STAFFBOT_LLM_TOKEN", "")
    if not base or not token:
        return json.dumps({"error": "StaffBot platform is not configured for this agent."})
    url = f"{base}/api/v1/agent-tools{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail")
        except Exception:
            detail = None
        return json.dumps({"error": detail or f"HTTP {e.code}", "status": e.code})
    except (urllib.error.URLError, TimeoutError) as e:
        return json.dumps({"error": f"StaffBot platform unreachable: {e}"})


def _schema(name, description, properties, required=()):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required)}}


TOOLS = [
    (_schema("staffbot_create_task", "Create a task in the customer's StaffBot task list (visible in their portal).", {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
        "assigned_to": {"type": "string", "description": "Person or AI staff responsible"},
     }, ["title"]),
     lambda p, **_: _call("POST", "/tasks", p)),
    (_schema("staffbot_list_tasks", "List the customer's StaffBot tasks, newest first.", {
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
        "limit": {"type": "integer"},
     }),
     lambda p, **_: _call("GET", "/tasks", query={"status": p.get("status"), "limit": p.get("limit")})),
    (_schema("staffbot_update_task", "Update a StaffBot task's status, priority, description or assignee.", {
        "task_id": {"type": "integer"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
        "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
        "description": {"type": "string"},
        "assigned_to": {"type": "string"},
     }, ["task_id"]),
     lambda p, **_: _call("PATCH", f"/tasks/{int(p['task_id'])}", {k: v for k, v in p.items() if k != "task_id"})),
    (_schema("staffbot_list_webhooks", "List the business APIs (webhooks) the customer has connected in StaffBot, e.g. WordPress, ERPNext, CRM.", {}),
     lambda p, **_: _call("GET", "/webhooks")),
    (_schema("staffbot_call_webhook",
             "Call one of the customer's connected business APIs. Authentication is added by the platform; never ask for or include API keys.", {
        "endpoint_name": {"type": "string", "description": "Name from staffbot_list_webhooks"},
        "path": {"type": "string", "description": "Path under the API's base URL, e.g. /wp/v2/posts"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "body": {"type": "object"},
        "query_params": {"type": "object"},
     }, ["endpoint_name", "path"]),
     lambda p, **_: _call("POST", "/webhook", p)),
    (_schema("staffbot_send_email", "Send an email from the customer's own mailbox (SMTP settings in their StaffBot portal).", {
        "to": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string", "description": "Plain text or HTML"},
        "cc": {"type": "string"},
     }, ["to", "subject", "body"]),
     lambda p, **_: _call("POST", "/email", p)),
]


def register(ctx):
    for schema, handler in TOOLS:
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler)
