"""Behaviour checks for S-04 (real Postgres) and S-05 (gateway side)."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, asyncio, hashlib, hmac, types

os.environ["AUTH_KEY"] = "master"
os.environ["DATABASE_URL"] = TEST_DB
sys.path.insert(0, os.path.join(REPO, "server-b", "gateway"))

import docker
class FakeContainer:
    def __init__(self, name, labels): self.name, self.labels = name, labels
class FakeContainers:
    store = {"staffbot-7": FakeContainer("staffbot-7", {"staffbot.type": "client", "staffbot.client_id": "7"}),
             "staffbot-db": FakeContainer("staffbot-db", {})}
    def get(self, name):
        if name not in self.store: raise docker.errors.NotFound("x")
        return self.store[name]
docker.from_env = lambda: types.SimpleNamespace(containers=FakeContainers())

import main as gw
from fastapi import HTTPException
import asyncpg

results = []
def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

async def s04():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("DROP TABLE IF EXISTS client_memory")
    await conn.execute("CREATE TABLE client_memory (id serial, client_id int, content text, metadata jsonb default '{}', created_at timestamp default now())")
    await conn.execute("INSERT INTO client_memory (client_id, content) VALUES (1,'harga kotak saiz L'),(2,'RAHSIA tenant dua'),(1,'diskaun 50% hari raya')")
    r = await gw._graph_search(conn, 1, "harga kotak", 10)
    check("S-04 normal keyword search works", [x["content"] for x in r] == ["harga kotak saiz L"], r)
    inj = "x%')OR(client_id>0)OR(content/**/ILIKE/**/'"
    r = await gw._graph_search(conn, 1, inj, 10)
    check("S-04 injection payload returns no other-tenant rows", all("RAHSIA" not in x["content"] for x in r), r)
    r = await gw._graph_search(conn, 1, "50%", 10)
    check("S-04 '%' treated literally", [x["content"] for x in r] == ["diskaun 50% hari raya"], r)
    r = await gw._graph_search(conn, 1, "a_c", 10)
    check("S-04 '_' treated literally (no match)", r == [], r)
    await conn.close()
asyncio.run(s04())

# S-05
own = gw.client_token(7)
check("S-05 gateway token == API derivation", own == hmac.new(b"master", b"staffbot-client:7", hashlib.sha256).hexdigest())
def ok(key, cid):
    try: gw.verify_master_or_client(key, cid); return True
    except HTTPException: return False
check("S-05 master key accepted", ok("master", 7))
check("S-05 own client token accepted", ok(own, 7))
check("S-05 token for other client rejected", not ok(own, 8))
check("S-05 missing key rejected", not ok(None, 7))
try:
    asyncio.run(gw.verify_auth(own)); check("S-05 client token rejected on master-only endpoints", False)
except HTTPException as e:
    check("S-05 client token rejected on master-only endpoints", e.status_code == 401)
check("S-05 client container allowed", gw._get_client_container("staffbot-7").name == "staffbot-7")
try:
    gw._get_client_container("staffbot-db"); check("S-05 non-client container refused", False)
except HTTPException as e:
    check("S-05 non-client container refused", e.status_code == 403)
r = asyncio.run(gw.container_status("staffbot-404"))
check("S-05 status of missing container unchanged ({status: not_found})", r == {"status": "not_found"}, r)

print("\n%d/%d passed" % (sum(ok_ for _, ok_ in results), len(results)))
sys.exit(0 if all(ok_ for _, ok_ in results) else 1)
