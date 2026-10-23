"""Channel router: WhatsApp/Telegram/web -> customer's Hermes API, with fakes for Hermes and managers."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, json, asyncio, threading, time
os.environ.update({"STAFFBOT_DATABASE_URL": TEST_DB, "STAFFBOT_SECRET_KEY": "k",
                   "STAFFBOT_LLM_PROXY_SECRET": "p", "STAFFBOT_CUSTOMER_GATEWAY_IP": "127.0.0.1",
                   "STAFFBOT_BAILEYS_MANAGER_URL": "http://127.0.0.1:8791", "STAFFBOT_TELEGRAM_MANAGER_URL": "http://127.0.0.1:8791",
                   "STAFFBOT_CHANNEL_INCOMING_KEY": "gwkey", "STAFFBOT_MANAGED_HERMES_ENABLED": "true"})
sys.path.insert(0, API_DIR)
import asyncpg, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

# fake Hermes API server: remembers history per session id
hermes = FastAPI(); hist = {}; seen = []
@hermes.post("/v1/chat/completions")
async def hc(req: Request):
    if req.headers.get("authorization") != "Bearer HKEY": return JSONResponse(status_code=401, content={})
    body = await req.json(); sid = req.headers["x-hermes-session-id"]; seen.append(dict(req.headers))
    msg = body["messages"][-1]["content"]; hist.setdefault(sid, []).append(msg)
    if body.get("stream"):
        async def gen():
            await asyncio.sleep(1.2)  # longer than the test keepalive
            yield f"data: {json.dumps({'choices':[{'delta':{'content':'jawapan web'}}]})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {"choices": [{"message": {"role": "assistant", "content": f"[{len(hist[sid])}] {msg}"}}]}
threading.Thread(target=lambda: uvicorn.run(hermes, port=8790, log_level="error"), daemon=True).start()
# fake managers (WhatsApp + Telegram send endpoints)
mgr = FastAPI(); sent = []
@mgr.post("/api/session/{cid}/send")
async def wa(cid: int, req: Request): sent.append(("wa", cid, await req.json())); return {"success": True}
@mgr.post("/api/send/{cid}")
async def tg(cid: int, req: Request): sent.append(("tg", cid, await req.json())); return {"success": True}
threading.Thread(target=lambda: uvicorn.run(mgr, port=8791, log_level="error"), daemon=True).start()
time.sleep(1.5)

import app.main, app.database as adb
asyncio.run(adb.init_db()); asyncio.run(adb.engine.dispose())
from app.utils.encryption import encrypt_value
DB = TEST_DB
async def sql(q, *a, fetch=False):
    c = await asyncpg.connect(DB)
    try: return await (c.fetch(q, *a) if fetch else c.execute(q, *a))
    finally: await c.close()
async def seed():
    await sql("TRUNCATE clients, packages RESTART IDENTITY CASCADE")
    await sql("""INSERT INTO packages (name,price_monthly,channel_limits) VALUES ('starter',49,'{"web":true,"whatsapp":1,"telegram":1}'),('trial',0,'{"web":true,"whatsapp":0,"telegram":0}')""")
    for n, p in (("a", "starter"), ("b", "trial"), ("c", "starter")):
        await sql("INSERT INTO clients (name,email,package,status,llm_token_version,created_at,updated_at) VALUES ($1,$2,$3,'active',1,now(),now())", n, n + "@x", p)
    for cid, st in ((1, "running"), (2, "running"), (3, "sleeping")):
        await sql("INSERT INTO hermes_instances (client_id,container_name,volume_name,image,api_port,api_server_key_encrypted,status) VALUES ($1,'c','v','i',8790,$2,$3)", cid, encrypt_value("HKEY"), st)
asyncio.run(seed())

from app.services import channel_router, hermes_orchestrator as orch
woken = []
async def fake_wake(db, client_id, dk=None):
    woken.append(client_id)
    await sql("UPDATE hermes_instances SET status='running' WHERE client_id=$1", client_id)
    return (await orch._load(db, client_id))[2]
orch.wake = fake_wake

res = []
def check(n, c, i=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{str(i)[:180]}]" if i else ""))

from fastapi.testclient import TestClient
from app.main import app as api
from app.utils.security import create_access_token
with TestClient(api) as c:
    r = c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message", "text": "hai", "jid": "60123@s.whatsapp.net"})
    check("incoming without key -> 401", r.status_code == 401)
    r = c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message", "text": "hai", "jid": "60123@s.whatsapp.net"}, headers={"x-gateway-key": "gwkey"})
    check("incoming accepted", r.status_code == 200 and r.json()["queued"])
    time.sleep(1)
    check("WhatsApp reply delivered via manager", sent and sent[-1] == ("wa", 1, {"to": "60123@s.whatsapp.net", "text": "[1] hai"}), sent)
    c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message", "text": "lagi", "jid": "60123@s.whatsapp.net"}, headers={"x-gateway-key": "gwkey"})
    time.sleep(1)
    check("same chat keeps one Hermes session (history server-side)", sent[-1][2]["text"] == "[2] lagi", sent[-1])
    check("session headers sent", seen[-1]["x-hermes-session-id"].startswith("sb-whatsapp-") and seen[-1]["x-hermes-session-key"].startswith("agent:main:whatsapp:"))

    n = len(sent)
    c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message", "text": "group", "jid": "x@g.us", "isGroup": True}, headers={"x-gateway-key": "gwkey"})
    c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "connection_update", "status": "open"}, headers={"x-gateway-key": "gwkey"})
    time.sleep(0.8)
    check("groups and non-message events ignored", len(sent) == n)

    c.post("/api/v1/channels/incoming/whatsapp/2", json={"type": "message", "text": "hai", "jid": "6011@s.whatsapp.net"}, headers={"x-gateway-key": "gwkey"})
    time.sleep(0.8)
    check("channel not in package -> no reply", len(sent) == n)

    c.post("/api/v1/channels/incoming/telegram/3", json={"type": "message", "text": "x" * 9000, "chat_id": 555, "chat_type": "private"}, headers={"x-gateway-key": "gwkey"})
    time.sleep(1.5)
    tg = [s for s in sent if s[0] == "tg"]
    check("sleeping container woken before Telegram message", woken == [3], woken)
    check("long Telegram reply split into <=4000-char chunks", len(tg) == 3 and all(len(s[2]["text"]) <= 4000 for s in tg), [len(s[2]["text"]) for s in tg])

    # web chat stream with keepalive
    channel_router_stream = channel_router.stream
    async def fast_keepalive(cid, chat, text):
        async for b in channel_router_stream(cid, chat, text, keepalive=0.3): yield b
    channel_router.stream = fast_keepalive
    H = {"Authorization": "Bearer " + create_access_token({"sub": "a@x", "role": "customer"})}
    r = c.post("/api/v1/channels/web/chat", json={"message": "hello", "conversation": "kerja"}, headers=H)
    check("web chat streams answer", r.status_code == 200 and "jawapan web" in r.text and "[DONE]" in r.text, r.text[-200:])
    check("keepalive comments sent while agent works", ": keepalive" in r.text)
    check("web session separate from WhatsApp", seen[-1]["x-hermes-session-id"].startswith("sb-web-"))
    r = c.post("/api/v1/channels/web/chat", json={"message": "x", "conversation": "../bad"}, headers=H)
    check("bad conversation id rejected", r.status_code == 422)
    r = c.post("/api/v1/channels/web/chat", json={"message": "x"})
    check("web chat needs login", r.status_code == 401)

    # Hermes down -> apologetic reply, not silence
    asyncio.run(sql("UPDATE hermes_instances SET api_port=8799 WHERE client_id=1"))  # nothing listens there
    async def wake_fail(db, client_id, dk=None): raise orch.OrchestratorError("down")
    orch.wake = wake_fail
    c.post("/api/v1/channels/incoming/whatsapp/1", json={"type": "message", "text": "ada?", "jid": "60123@s.whatsapp.net"}, headers={"x-gateway-key": "gwkey"})
    time.sleep(1.2)
    check("agent down -> polite fallback reply", "Maaf" in sent[-1][2]["text"], sent[-1])
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
