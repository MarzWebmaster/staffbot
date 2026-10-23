"""Migration script + legacy forwarding for non-migrated customers."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, asyncio, tempfile, threading, time, subprocess
S = tempfile.mkdtemp()
os.environ.update({"STAFFBOT_DATABASE_URL": TEST_DB, "STAFFBOT_SECRET_KEY": "k",
                   "STAFFBOT_LLM_PROXY_SECRET": "p", "STAFFBOT_HERMES_MANAGED_DIR": S + "/m", "STAFFBOT_HERMES_BACKUP_DIR": S + "/b",
                   "STAFFBOT_CHANNEL_INCOMING_KEY": "gwkey", "STAFFBOT_SERVER_B_API_URL": "http://127.0.0.1:8785"})
sys.path.insert(0, API_DIR)
import asyncpg, uvicorn, docker
from fastapi import FastAPI, Request
legacy = FastAPI(); got = []
@legacy.post("/api/incoming/{platform}/{cid}")
async def li(platform: str, cid: int, req: Request): got.append((platform, cid, req.headers.get("x-gateway-key"), await req.json())); return {"success": True}
threading.Thread(target=lambda: uvicorn.run(legacy, port=8785, log_level="error"), daemon=True).start(); time.sleep(1)

import app.main, app.database as adb
asyncio.run(adb.init_db()); asyncio.run(adb.engine.dispose())
from app.utils.encryption import encrypt_value
DB = TEST_DB
async def sql(q, *a, fetch=False):
    c = await asyncpg.connect(DB)
    try: return await (c.fetch(q, *a) if fetch else c.execute(q, *a))
    finally: await c.close()
async def seed():
    await sql("TRUNCATE clients, packages, llm_providers RESTART IDENTITY CASCADE")
    await sql("CREATE TABLE IF NOT EXISTS client_memory (id serial, client_id int, content text, metadata jsonb default '{}', created_at timestamp default now())")
    await sql("DELETE FROM client_memory")
    await sql("INSERT INTO packages (name,price_monthly,channel_limits) VALUES ('starter',49,'{\"web\":true,\"whatsapp\":1}')")
    await sql("INSERT INTO clients (name,company,email,package,status,llm_token_version,created_at,updated_at) VALUES ('Ali','Kedai Ali','a@x','starter','active',1,now(),now()),('B','B Sdn','b@x','starter','active',1,now(),now())")
    await sql("""INSERT INTO client_memory (client_id, content, metadata) VALUES (1,'Harga kotak L RM2.50','{"memory_type":"fact"}'),(1,'Bos suka jawapan ringkas','{"memory_type":"preference"}'),(2,'Rahsia B','{}')""")
asyncio.run(seed())

res = []
def check(n, c, i=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{str(i)[:220]}]" if i else ""))

# legacy forwarding before migration
from fastapi.testclient import TestClient
with TestClient(app.main.app) as c:
    r = c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message", "text": "hai", "jid": "6012@s"}, headers={"x-gateway-key": "gwkey"})
    check("non-migrated customer forwarded to legacy gateway", r.json().get("legacy") and got and got[-1][:3] == ("whatsapp", 1, "gwkey"), (r.json(), got))
    r = c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message"}, headers={"x-gateway-key": "nope"})
    check("forwarding still requires the key", r.status_code == 401)

# dry run
out = subprocess.run([sys.executable, "-m", "scripts.migrate_to_managed_hermes", "--clients", "1"], cwd=API_DIR, capture_output=True, text=True, env=os.environ)
check("dry run reports and changes nothing", "memories=2" in out.stdout and "dry run" in out.stdout and not asyncio.run(sql("SELECT 1 FROM hermes_instances", fetch=True)), out.stdout + out.stderr[-300:])

# apply with fake docker
class NF(docker.errors.NotFound):
    def __init__(self): Exception.__init__(self, "nf")
helper = []
class C:
    def __init__(s, kw): s.kw, s.status, s.attrs = kw, "running", {"NetworkSettings": {"Ports": {"8642/tcp": [{"HostPort": "40100"}]}}}
    def reload(s): pass
class Containers:
    store = {}
    def get(s, n):
        if n not in s.store: raise NF()
        return s.store[n]
    def run(s, image=None, *a, **kw):
        if kw.get("remove"):
            stage = [h for h, b in kw["volumes"].items() if b["bind"] == "/stage"][0]
            files = {os.path.relpath(os.path.join(r, f), stage): open(os.path.join(r, f)).read() for r, _, fs in os.walk(stage) for f in fs}
            helper.append((a, kw, files)); return None
        kw["image"] = image; c = C(kw); s.store[kw["name"]] = c; return c
class Coll:
    def __init__(s): s.store = {}
    def get(s, n):
        if n not in s.store: raise NF()
        return s.store[n]
    def create(s, n, **kw): s.store[n] = kw
class DK: containers = Containers(); networks = Coll(); volumes = Coll()
from app.services import hermes_orchestrator as orch
orch._docker = lambda: DK()
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import app.services.audit as _audit
adb.engine = create_async_engine(adb.db_url)
adb.async_session_factory = async_sessionmaker(adb.engine, class_=AsyncSession, expire_on_commit=False)
if hasattr(_audit, "async_session_factory"): _audit.async_session_factory = adb.async_session_factory
sys.argv = ["x", "--clients", "1", "--apply"]
import scripts.migrate_to_managed_hermes as mig
asyncio.run(mig.main())
inst = asyncio.run(sql("SELECT status FROM hermes_instances WHERE client_id=1", fetch=True))
check("customer 1 provisioned", inst and inst[0]["status"] == "running", inst)
files = helper[-1][2] if helper else {}
skill, know = files.get("skills/staffbot-imported/company-knowledge/SKILL.md", ""), files.get("skills/staffbot-imported/company-knowledge/references/knowledge.md", "")
check("knowledge skill written with frontmatter", skill.startswith("---\nname: company-knowledge") and "Kedai Ali" in skill, skill[:200])
check("memories grouped by type, only this customer's", "## fact" in know and "Harga kotak L RM2.50" in know and "## preference" in know and "Rahsia B" not in know, know)
cmd = helper[-1][0][0][2] if helper else ""
check("helper copies then chowns to hermes uid, no network", "chown -R 10000:10000 /data/skills" in cmd and helper[-1][1]["network_disabled"], cmd)
check("staging dir cleaned up", not os.path.exists(os.path.join(S, "b", "_staging", "1")))
try:
    orch.write_files_to_volume(1, {"../etc/passwd": "x"}, dk=DK()); bad = False
except orch.OrchestratorError: bad = True
check("path escape rejected", bad)
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
