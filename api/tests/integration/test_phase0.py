import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, asyncio, subprocess
os.environ.update({"STAFFBOT_DATABASE_URL": TEST_DB, "STAFFBOT_SECRET_KEY": "k",
                   "STAFFBOT_ADMIN_EMAIL": "admin@staffbot.my", "STAFFBOT_SERVER_B_API_KEY": "srv"})
API = API_DIR; sys.path.insert(0, API)
VENV = os.path.dirname(sys.executable)
import asyncpg
from app.utils.security import hash_password, create_access_token
res = []
def check(n, c, i=""): res.append(c); print(("PASS " if c else "FAIL ") + n + (f"  [{i}]" if i else ""))

NEW = ["memory_retention_days","memory_item_limit","knowledge_item_limit","allowed_models","channel_limits","byok_allowed",
       "console_mode","agent_terminal","catalog_tier","custom_code_allowed","idle_sleep_minutes","backup_retention_days",
       "upgrade_window","support_level"]
async def sql(q, *a, fetch=False):
    c = await asyncpg.connect(TEST_DB)
    try: return await (c.fetch(q, *a) if fetch else c.execute(q, *a))
    finally: await c.close()

# 1. Create schema, then remove the new columns to simulate the pre-migration production DB
import app.main  # registers all models
from app.database import init_db
asyncio.run(init_db())
import app.database as _adb
asyncio.run(_adb.engine.dispose())
for col in NEW: asyncio.run(sql(f"ALTER TABLE packages DROP COLUMN {col}"))
asyncio.run(sql("INSERT INTO packages (name, display_name, price_monthly, managed_tokens) VALUES ('starter','Starter',49,100000)"))

# 2. Migrate: stamp baseline, upgrade head, run twice (idempotent)
alembic = os.path.join(VENV, "alembic")
r1 = subprocess.run([alembic, "stamp", "0001_baseline"], cwd=API, capture_output=True, text=True)
r2 = subprocess.run([alembic, "upgrade", "head"], cwd=API, capture_output=True, text=True)
check("alembic stamp + upgrade ok", r1.returncode == 0 and r2.returncode == 0, (r1.stderr + r2.stderr)[-300:])
cols = {r["column_name"] for r in asyncio.run(sql("SELECT column_name FROM information_schema.columns WHERE table_name='packages'", fetch=True))}
check("all new columns exist", set(NEW) <= cols, set(NEW) - cols)
row = asyncio.run(sql("SELECT console_mode, idle_sleep_minutes, byok_allowed FROM packages WHERE name='starter'", fetch=True))[0]
check("existing row gets defaults", (row["console_mode"], row["idle_sleep_minutes"], row["byok_allowed"]) == ("none", 30, True), dict(row))
r3 = subprocess.run([alembic, "downgrade", "0001_baseline"], cwd=API, capture_output=True, text=True)
r4 = subprocess.run([alembic, "upgrade", "head"], cwd=API, capture_output=True, text=True)
check("downgrade + re-upgrade ok", r3.returncode == 0 and r4.returncode == 0, (r3.stderr + r4.stderr)[-300:])

# 3. Seed script dry run / apply
r = subprocess.run([sys.executable, "-m", "scripts.seed_packages_v1"], cwd=API, capture_output=True, text=True)
check("seed dry run writes nothing", "dry run" in r.stdout and len(asyncio.run(sql("SELECT 1 FROM packages", fetch=True))) == 1, r.stdout + r.stderr[-300:])
r = subprocess.run([sys.executable, "-m", "scripts.seed_packages_v1", "--apply"], cwd=API, capture_output=True, text=True)
names = {x["name"]: x for x in asyncio.run(sql("SELECT name, price_monthly, managed_tokens, idle_sleep_minutes FROM packages", fetch=True))}
check("seed creates missing, keeps existing starter price", set(names) == {"trial","starter","professional","enterprise"} and names["starter"]["managed_tokens"] == 100000, r.stdout + r.stderr[-300:])
check("enterprise always-on stored as 0", names["enterprise"]["idle_sleep_minutes"] == 0)

# 4. CRUD through the API
from fastapi.testclient import TestClient
asyncio.run(_adb.engine.dispose())
from app.main import app
async def seed_admin():
    await sql("INSERT INTO clients (name,email,password_hash,package,status) VALUES ('Admin','admin@staffbot.my',$1,'enterprise','active'),('C','c@x.my',$1,'professional','active')", hash_password("x"))
asyncio.run(seed_admin())
H = {"Authorization": "Bearer " + create_access_token({"sub": "admin@staffbot.my", "role": "admin"})}
with TestClient(app) as c:
    body = {"name": "business", "display_name": "Business", "price_monthly": 299, "console_mode": "shell",
            "agent_terminal": True, "channel_limits": {"web": True, "whatsapp": 3}, "allowed_models": ["deepseek-chat"],
            "idle_sleep_minutes": 0, "support_level": "priority"}
    r = c.post("/api/v1/admin/packages", json=body, headers=H)
    check("B-11: create package 201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    pid = r.json().get("id")
    r = c.post("/api/v1/admin/packages", json=body, headers=H)
    check("duplicate name -> 409", r.status_code == 409, r.status_code)
    r = c.post("/api/v1/admin/packages", json={**body, "name": "bad", "console_mode": "root"}, headers=H)
    check("invalid console_mode -> 422", r.status_code == 422, r.status_code)
    allp = {p["name"]: p for p in c.get("/api/v1/admin/packages/all", headers=H).json()}
    b = allp["business"]
    check("read returns new fields", b["console_mode"] == "shell" and b["channel_limits"]["whatsapp"] == 3 and b["allowed_models"] == ["deepseek-chat"] and b["idle_sleep_minutes"] == 0, b)
    r = c.put(f"/api/v1/admin/packages/{pid}", json={"idle_sleep_minutes": 45, "console_mode": "hermes", "price_monthly": 279}, headers=H)
    b = {p["name"]: p for p in c.get("/api/v1/admin/packages/all", headers=H).json()}["business"]
    check("update fields", r.status_code == 200 and b["idle_sleep_minutes"] == 45 and b["console_mode"] == "hermes" and b["price_monthly"] == 279, b)
    c.put(f"/api/v1/admin/packages/{pid}", json={"idle_sleep_minutes": 0}, headers=H)
    b = {p["name"]: p for p in c.get("/api/v1/admin/packages/all", headers=H).json()}["business"]
    check("update idle 0 -> always on", b["idle_sleep_minutes"] == 0, b["idle_sleep_minutes"])
    prof = allp["professional"]["id"]
    r = c.delete(f"/api/v1/admin/packages/{prof}", headers=H)
    check("delete package in use -> 409", r.status_code == 409, r.text[:120])
    r = c.delete(f"/api/v1/admin/packages/{pid}", headers=H)
    check("delete unused package -> 200", r.status_code == 200, r.text[:120])
    cust = {"Authorization": "Bearer " + create_access_token({"sub": "c@x.my", "role": "customer"})}
    r = c.post("/api/v1/admin/packages", json={**body, "name": "x2"}, headers=cust)
    check("customer cannot create package", r.status_code == 403, r.status_code)
    r = c.get("/api/v1/packages/public")
    check("public packages endpoint ok", r.status_code == 200, r.status_code)
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
