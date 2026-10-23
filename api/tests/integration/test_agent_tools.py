"""agent-tools API (served by the LLM proxy) + the Hermes plugin as a real HTTP client."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, json, asyncio, threading, time, importlib.util
os.environ.update({"STAFFBOT_DATABASE_URL": TEST_DB, "STAFFBOT_SECRET_KEY": "k",
                   "STAFFBOT_LLM_PROXY_SECRET": "proxysecret"})
sys.path.insert(0, API_DIR)
import asyncpg, uvicorn
from fastapi import FastAPI, Request

# target "business API"
biz = FastAPI(); hits = []
@biz.api_route("/wp-json/{p:path}", methods=["GET", "POST"])
async def wp(p: str, req: Request):
    hits.append({"path": p, "auth": req.headers.get("authorization"), "q": dict(req.query_params)})
    return {"ok": True, "echo_secret": "WP-SECRET-123", "path": p}
threading.Thread(target=lambda: uvicorn.run(biz, port=8798, log_level="error"), daemon=True).start()

import app.main, app.database as adb
asyncio.run(adb.init_db()); asyncio.run(adb.engine.dispose())
from app.utils.encryption import encrypt_value
DB = TEST_DB
async def sql(q, *a, fetch=False):
    c = await asyncpg.connect(DB)
    try: return await (c.fetch(q, *a) if fetch else c.execute(q, *a))
    finally: await c.close()
async def seed():
    await sql("TRUNCATE clients RESTART IDENTITY CASCADE")
    for n, st in (("a", "active"), ("b", "active"), ("c", "suspended")):
        await sql("INSERT INTO clients (name,email,package,status,llm_token_version,created_at,updated_at) VALUES ($1,$2,'starter',$3,1,now(),now())", n, n + "@x", st)
    await sql("INSERT INTO client_webhooks (client_id,name,base_url,auth_type,auth_value,default_headers,is_active,rate_limit,max_timeout,created_at) VALUES "
              "(1,'wp','http://127.0.0.1:8798/wp-json','bearer',$1,'{}',true,10,30,now()),"
              "(1,'meta','http://169.254.169.254/latest','none',NULL,'{}',true,10,30,now()),"
              "(2,'wp','http://127.0.0.1:8798/wp-json','none',NULL,'{}',true,10,30,now())", encrypt_value("WP-SECRET-123"))
    await sql("INSERT INTO client_email_configs (client_id,smtp_host,smtp_port,smtp_user,smtp_pass,use_tls,from_email,from_name,is_active,created_at) VALUES (1,'smtp.x',587,'u@x',$1,true,'u@x','Kedai A',true,now())", encrypt_value("SMTPPASS"))
asyncio.run(seed())

from app.llm_proxy.main import app as proxy
from app.llm_proxy.tokens import make_token
from app.services import agent_tools
threading.Thread(target=lambda: uvicorn.run(proxy, port=8797, log_level="error"), daemon=True).start()
time.sleep(2)

res = []
def check(n, c, i=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{str(i)[:180]}]" if i else ""))

# Load the plugin the way Hermes would, with a fake ctx
spec = importlib.util.spec_from_file_location("staffbot_plugin", os.path.join(REPO, "hermes-core", "plugins", "staffbot", "__init__.py"))
plug = importlib.util.module_from_spec(spec); spec.loader.exec_module(plug)
tools = {}
class Ctx:
    def register_tool(self, name, toolset, schema, handler): tools[name] = (toolset, schema, handler)
plug.register(Ctx())
check("plugin registers 6 tools in toolset 'staffbot'", len(tools) == 6 and all(t[0] == "staffbot" for t in tools.values()), sorted(tools))
check("tool schemas are valid JSON-schema objects", all(t[1]["parameters"]["type"] == "object" and t[1]["description"] for t in tools.values()))
call = lambda name, **p: json.loads(tools[name][2](p))

os.environ["STAFFBOT_API_URL"] = "http://127.0.0.1:8797"
os.environ.pop("STAFFBOT_LLM_TOKEN", None)
check("plugin without config returns clear error", "not configured" in call("staffbot_list_tasks").get("error", ""))
os.environ["STAFFBOT_LLM_TOKEN"] = "sbk_1_1_" + "0" * 64
check("bad token -> error", call("staffbot_list_tasks").get("status") == 401)
os.environ["STAFFBOT_LLM_TOKEN"] = make_token(3, 1)
check("suspended customer -> 403", call("staffbot_list_tasks").get("status") == 403)

os.environ["STAFFBOT_LLM_TOKEN"] = make_token(1, 1)
t = call("staffbot_create_task", title="Hantar sebut harga", priority="high")
check("create task", t.get("id") and t["priority"] == "high" and t["status"] == "pending", t)
u = call("staffbot_update_task", task_id=t["id"], status="completed")
check("update task", u.get("status") == "completed", u)
check("list tasks", len(json.loads(tools["staffbot_list_tasks"][2]({}))) == 1)
os.environ["STAFFBOT_LLM_TOKEN"] = make_token(2, 1)
check("tenant isolation: customer 2 cannot see/update customer 1 task",
      json.loads(tools["staffbot_list_tasks"][2]({})) == [] and call("staffbot_update_task", task_id=t["id"], status="cancelled").get("status") == 404)

os.environ["STAFFBOT_LLM_TOKEN"] = make_token(1, 1)
check("list webhooks (no secrets exposed)", [w["name"] for w in json.loads(tools["staffbot_list_webhooks"][2]({}))] == ["wp", "meta"] and "SECRET" not in tools["staffbot_list_webhooks"][2]({}))
r = call("staffbot_call_webhook", endpoint_name="wp", path="/wp/v2/posts")
check("SSRF: localhost webhook blocked", r.get("status") == 403, r)
r = call("staffbot_call_webhook", endpoint_name="meta", path="/meta-data")
check("SSRF: metadata IP blocked", r.get("status") == 403, r)
r = call("staffbot_call_webhook", endpoint_name="wp", path="../../admin")
check("path traversal rejected", r.get("status") == 400, r)
r = call("staffbot_call_webhook", endpoint_name="wp", path="http://evil.com/x")
check("absolute URL in path rejected", r.get("status") == 400, r)
r = call("staffbot_call_webhook", endpoint_name="nope", path="/x")
check("unknown webhook -> 404 with guidance", r.get("status") == 404 and "portal" in r.get("error", ""), r)

# allow the local test host to exercise the success path
agent_tools.check_public_host = lambda h: None
r = call("staffbot_call_webhook", endpoint_name="wp", path="/wp/v2/posts", query_params={"per_page": 2})
check("webhook success: server adds auth, secret redacted in response",
      r.get("status_code") == 200 and hits[-1]["auth"] == "Bearer WP-SECRET-123" and hits[-1]["q"] == {"per_page": "2"} and "WP-SECRET-123" not in json.dumps(r), r)
for _ in range(9): call("staffbot_call_webhook", endpoint_name="wp", path="/x")
r = call("staffbot_call_webhook", endpoint_name="wp", path="/x")
check("webhook rate limit 10/min (DB-counted)", r.get("status") == 429, r)

# email with fake SMTP
sent = []
class FakeSMTP:
    def __init__(self, h, p, timeout=None): self.h = (h, p)
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def starttls(self): sent.append("tls")
    def login(self, u, p): sent.append(("login", u, p))
    def sendmail(self, f, rcpt, msg): sent.append(("send", f, rcpt))
agent_tools.smtplib.SMTP = FakeSMTP
r = call("staffbot_send_email", to="cust@y.my", subject="Sebut harga", body="Terima kasih")
check("email sent via customer's SMTP (password stays server-side)", r.get("sent") and ("login", "u@x", "SMTPPASS") in sent and "tls" in sent, r)
os.environ["STAFFBOT_LLM_TOKEN"] = make_token(2, 1)
r = call("staffbot_send_email", to="a@b", subject="s", body="b")
check("email without SMTP config -> 404 guidance", r.get("status") == 404, r)
audits = asyncio.run(sql("SELECT action, count(*) FROM audit_trail GROUP BY action", fetch=True))
check("audit rows for webhook + email", {a["action"] for a in audits} >= {"webhook_call", "email_send"}, [dict(a) for a in audits])

# pure URL builder
for base, path, ok in [("https://x.com/api", "/v1/a", True), ("https://x.com/api", "v1/../../b", False),
                       ("https://x.com/api", "//evil.com/a", False), ("https://x.com/api", "https://evil.com", False)]:
    try: agent_tools.build_webhook_url(base, path); got = True
    except agent_tools.ToolError: got = False
    check(f"build_webhook_url({path!r}) allowed={ok}", got == ok)
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
