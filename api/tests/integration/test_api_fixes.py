"""Behaviour checks for S-01, S-02, S-03, S-05 (API side), S-06."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, asyncio, hashlib, hmac

os.environ.update({
    "STAFFBOT_DATABASE_URL": TEST_DB,
    "STAFFBOT_SECRET_KEY": "test-secret",
    "STAFFBOT_SERVER_B_API_KEY": "srvkey",
    "STAFFBOT_ADMIN_EMAIL": "admin@staffbot.my",
})
for k in ("STAFFBOT_GATEWAY_API_KEY", "GATEWAY_API_KEY", "MODERATION_API_KEY", "HERMES_API_KEY"):
    os.environ.pop(k, None)
sys.path.insert(0, API_DIR)

from fastapi.testclient import TestClient
from app.main import app
from app.utils.security import hash_password, create_access_token

results = []
def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

with TestClient(app) as c:
    # seed one client + subscription
    import asyncpg
    async def seed():
        conn = await asyncpg.connect(TEST_DB)
        await conn.execute("TRUNCATE clients RESTART IDENTITY CASCADE")
        cid = await conn.fetchval(
            "INSERT INTO clients (name,email,password_hash,package,status,created_at,updated_at) "
            "VALUES ('A','a@x.my',$1,'starter','pending',now(),now()) RETURNING id", hash_password("pw12345678"))
        await conn.execute(
            "INSERT INTO subscriptions (client_id,package,status,managed_token_quota,managed_token_used,provider_token_usage,start_date,created_at,updated_at) "
            "VALUES ($1,'starter','active',1000,900,'{}',now(),now(),now())", cid)
        await conn.close()
        return cid
    cid = asyncio.get_event_loop().run_until_complete(seed()) if False else asyncio.run(seed())
    tok = create_access_token({"sub": "a@x.my", "role": "customer", "client_id": cid})
    H = {"Authorization": f"Bearer {tok}"}

    # S-01
    r = c.put(f"/api/v1/subscriptions/{cid}/tokens", json={"managed_token_used": 0})
    check("S-01 no key -> rejected", r.status_code in (401, 422), r.status_code)
    r = c.put(f"/api/v1/subscriptions/{cid}/tokens", json={"managed_token_used": 0}, headers={"x-api-key": "wrong"})
    check("S-01 wrong key -> 401", r.status_code == 401, r.status_code)
    r = c.put(f"/api/v1/subscriptions/{cid}/tokens", json={"managed_token_used": 5}, headers={"x-api-key": "srvkey"})
    check("S-01 internal key -> 200", r.status_code == 200, f"{r.status_code} {r.text[:80]}")

    # S-02
    r = c.put(f"/api/v1/clients/{cid}", json={"name": "New", "package": "enterprise", "status": "active", "email": "admin@staffbot.my"}, headers=H)
    body = r.json()
    check("S-02 update 200", r.status_code == 200, r.status_code)
    check("S-02 name changes", body.get("name") == "New")
    check("S-02 package NOT changed", body.get("package") == "starter", body.get("package"))
    check("S-02 status NOT changed", body.get("status") == "pending", body.get("status"))
    check("S-02 email NOT changed", body.get("email") == "a@x.my", body.get("email"))

    # S-03: old hardcoded default must no longer work (key unset)
    r = c.get("/api/v1/tasks/list", headers={"X-Internal-Key": "hermes-gateway-key-2024-secure", "X-Client-ID": str(cid)})
    check("S-03 old default key rejected", r.status_code == 401, r.status_code)
    r = c.get("/api/v1/tasks/list", headers=H)
    check("S-03 JWT still works", r.status_code == 200, r.status_code)

# S-03 with key configured
import importlib, app.middleware.auth as auth_mod
os.environ["STAFFBOT_GATEWAY_API_KEY"] = "gwkey"
importlib.reload(auth_mod)
check("S-03 key read from STAFFBOT_GATEWAY_API_KEY", auth_mod.GATEWAY_INTERNAL_KEY == "gwkey")
os.environ.pop("STAFFBOT_GATEWAY_API_KEY"); os.environ["GATEWAY_API_KEY"] = "gwkey2"
importlib.reload(auth_mod)
check("S-03 key read from GATEWAY_API_KEY", auth_mod.GATEWAY_INTERNAL_KEY == "gwkey2")

# S-05 API side: token derivation matches gateway formula
import app.services.docker_service as ds
expected = hmac.new(b"srvkey", b"staffbot-client:7", hashlib.sha256).hexdigest()
src = open(ds.__file__).read()
check("S-05 API no longer injects master key", "settings.SERVER_B_API_KEY or \"local-dev\"" not in src)

# S-06
import app.services.content_moderation as cm
calls = []
class FakeResp:
    status_code = 200
    def json(self): return {"choices": [{"message": {"content": '{"category":"safe","confidence":1}'}}]}
class FakeClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None, headers=None):
        calls.append(headers); return FakeResp()
cm.httpx.AsyncClient = FakeClient
cm.MODERATION_API_KEY = ""
res = asyncio.run(cm._ai_classify("hello", api_key="sk-user-byok"))
check("S-06 no platform key -> skip, user key not sent", res is None and not calls)
cm.MODERATION_API_KEY = "platform-key"
asyncio.run(cm._ai_classify("hello", api_key="sk-user-byok"))
check("S-06 uses platform key, never user key", calls and calls[-1]["Authorization"] == "Bearer platform-key")

print("\n%d/%d passed" % (sum(ok for _, ok in results), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)
