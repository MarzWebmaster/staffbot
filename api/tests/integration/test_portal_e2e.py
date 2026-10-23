"""Browser E2E: customer Hermes page (status, chat stream, Web Console) and admin Hermes page."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, json, asyncio, threading, time, socket
os.environ.update({"STAFFBOT_DATABASE_URL": TEST_DB, "STAFFBOT_SECRET_KEY": "k",
                   "STAFFBOT_LLM_PROXY_SECRET": "p", "STAFFBOT_CUSTOMER_GATEWAY_IP": "127.0.0.1",
                   "STAFFBOT_MANAGED_HERMES_ENABLED": "true", "STAFFBOT_ADMIN_EMAIL": "admin@staffbot.my"})
sys.path.insert(0, API_DIR)
import asyncpg, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

hermes = FastAPI()
@hermes.post("/v1/chat/completions")
async def hc(req: Request):
    body = await req.json(); msg = body["messages"][-1]["content"]
    async def gen():
        for part in ["Salam! ", "Anda tanya: ", msg]:
            await asyncio.sleep(0.2)
            yield f"data: {json.dumps({'choices':[{'delta':{'content':part}}]})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
threading.Thread(target=lambda: uvicorn.run(hermes, port=8790, log_level="error"), daemon=True).start()

import app.main, app.database as adb
asyncio.run(adb.init_db()); asyncio.run(adb.engine.dispose())
from app.utils.encryption import encrypt_value
from app.utils.security import create_access_token, hash_password
DB = TEST_DB
async def sql(q, *a, fetch=False):
    c = await asyncpg.connect(DB)
    try: return await (c.fetch(q, *a) if fetch else c.execute(q, *a))
    finally: await c.close()
async def seed():
    await sql("TRUNCATE clients, packages RESTART IDENTITY CASCADE")
    await sql("""INSERT INTO packages (name,display_name,price_monthly,channel_limits,console_mode,agent_terminal,idle_sleep_minutes,byok_allowed)
                 VALUES ('professional','Professional',149,'{"web":true,"whatsapp":2,"telegram":1}','shell',true,60,true),
                        ('trial','Percubaan',0,'{"web":true}','none',false,15,false)""")
    for n, e, p in (("Kedai Ali", "ali@x.my", "professional"), ("Trial Co", "t@x.my", "trial"), ("Admin", "admin@staffbot.my", "professional")):
        await sql("INSERT INTO clients (name,email,password_hash,package,status,llm_token_version,created_at,updated_at) VALUES ($1,$2,$3,$4,'active',1,now(),now())", n, e, hash_password("x"), p)
    for cid in (1, 2):
        await sql("INSERT INTO hermes_instances (client_id,container_name,volume_name,image,api_port,api_server_key_encrypted,status,last_active_at,created_at,updated_at) VALUES ($1,$2,'v','staffbot-hermes:0.22.4-sb1',8790,$3,'running',now(),now(),now())", cid, f"staffbot-hermes-{cid}", encrypt_value("HKEY"))
asyncio.run(seed())

# fake docker exec: an "echo shell" over a socketpair
from app.routers import agent_portal
from app.services import hermes_orchestrator as orch
execs = []
class FakeAPI:
    def exec_resize(self, exec_id, height, width): execs.append(("resize", width, height))
def fake_open_exec(container, mode, dk=None):
    a, b = socket.socketpair()
    execs.append(("open", container, mode))
    def shell():
        b.sendall(f"hermes@{container}:~$ ".encode())
        while True:
            d = b.recv(1024)
            if not d: break
            b.sendall(b"ECHO:" + d)
    threading.Thread(target=shell, daemon=True).start()
    a.setblocking(False)
    return type("DK", (), {"api": FakeAPI()})(), "exec1", a
agent_portal.open_exec = fake_open_exec
async def fake_wake(db, client_id, dk=None): return (await orch._load(db, client_id))[2]
orch.wake = fake_wake

threading.Thread(target=lambda: uvicorn.run(app.main.app, port=8766, log_level="error"), daemon=True).start()
time.sleep(2)

res = []
def check(n, c, i=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{str(i)[:200]}]" if i else ""))
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8766"
tok = lambda e: create_access_token({"sub": e, "role": "customer"})
S = __import__('tempfile').mkdtemp()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
    pg = b.new_page(viewport={"width": 1280, "height": 860}); errs = []
    pg.goto(BASE + "/customer/login.html"); pg.evaluate(f"localStorage.setItem('staffbot_token', '{tok('ali@x.my')}')")
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/customer/agent.html"); pg.wait_for_selector("#agentGrid", state="visible", timeout=15000)
    pg.wait_for_timeout(800)
    check("status shows Aktif + package", pg.inner_text("#statusPill") == "Aktif" and pg.inner_text("#fPkg") == "Professional", pg.inner_text("#statusPill"))
    check("channels listed from package", "WhatsApp ×2" in pg.inner_text("#fChannels"), pg.inner_text("#fChannels"))
    check("console button visible for shell plan", pg.is_visible("#consoleBtn"))
    pg.fill("#chatText", "Berapa stok kotak L?"); pg.click("#sendBtn")
    for _ in range(60):
        if "Anda tanya: Berapa stok" in pg.inner_text("#chatLog"): break
        pg.wait_for_timeout(250)
    check("chat answer streamed into page", "Salam! Anda tanya: Berapa stok kotak L?" in pg.inner_text("#chatLog"), pg.inner_text("#chatLog"))
    xterm_loaded = pg.evaluate("typeof Terminal !== 'undefined'")
    check("xterm.js loaded (vendored)", xterm_loaded)
    if xterm_loaded:
        pg.click("#consoleBtn"); pg.wait_for_timeout(1500)
        pg.keyboard.type("ls"); pg.wait_for_timeout(800)
        text = pg.evaluate("Array.from(document.querySelectorAll('.xterm-rows > div')).map(d => d.textContent).join('\\n')")
        check("console shows prompt from container", "hermes@staffbot-hermes-1" in text, text[:200])
        check("console round-trips keystrokes", "ECHO:l" in text and "ECHO:s" in text, text[:300])
        check("console opened shell in this customer's container", ("open", "staffbot-hermes-1", "shell") in execs and any(e[0] == "resize" for e in execs), execs)
        pg.screenshot(path=os.path.join(S, "agent_console.png"))
        pg.click("text=Tutup"); pg.wait_for_timeout(800)
    check("no JS errors on agent page", not errs, errs)

    # trial plan: console not allowed
    pg2 = b.new_page()
    pg2.goto(BASE + "/customer/login.html"); pg2.evaluate(f"localStorage.setItem('staffbot_token', '{tok('t@x.my')}')")
    pg2.goto(BASE + "/customer/agent.html"); pg2.wait_for_selector("#agentGrid", state="visible", timeout=15000); pg2.wait_for_timeout(600)
    check("trial: console hidden + note", not pg2.is_visible("#consoleBtn") and "tidak termasuk" in pg2.inner_text("#consoleNote"))
    import httpx
    def ticket(email):
        return httpx.post(BASE + "/api/v1/agent/console-ticket", headers={"Authorization": "Bearer " + tok(email)}).json()["ticket"]
    def ws_close(q):
        return pg2.evaluate("q => new Promise(r => { const s = new WebSocket('ws://127.0.0.1:8766/api/v1/agent/console?' + q); s.onclose = e => r(e.code); })", q)
    check("trial: console websocket refused (4403)", ws_close("ticket=" + ticket("t@x.my")) == 4403)
    check("bad ticket refused", ws_close("ticket=bad") == 4403)
    check("login JWT is not accepted as a console ticket", ws_close("ticket=" + tok("ali@x.my")) == 4403)
    t1 = ticket("ali@x.my")
    check("ticket cannot be used as an API bearer token", httpx.get(BASE + "/api/v1/agent/me", headers={"Authorization": "Bearer " + t1}).status_code == 401)
    pg2.evaluate("q => new Promise(r => { const s = new WebSocket('ws://127.0.0.1:8766/api/v1/agent/console?' + q); s.onopen = () => { s.close(); r(1); }; s.onclose = () => r(0); })", "ticket=" + t1)
    time.sleep(0.5)
    check("ticket is single-use (replay refused)", ws_close("ticket=" + t1) == 4403)

    # admin page
    pg3 = b.new_page(viewport={"width": 1280, "height": 800}); errs3 = []
    pg3.on("pageerror", lambda e: errs3.append(str(e)))
    pg3.goto(BASE + "/admin/login.html"); pg3.evaluate(f"localStorage.setItem('staffbot_token', '{create_access_token({'sub': 'admin@staffbot.my', 'role': 'admin'})}')")
    pg3.goto(BASE + "/admin/hermes.html"); pg3.wait_for_timeout(2500)
    rows = pg3.inner_text("#rows")
    check("admin lists both instances", "Kedai Ali" in rows and "Trial Co" in rows and "staffbot-hermes:0.22.4-sb1" in rows, rows[:200])
    check("admin sidebar has Hermes Agents", "Hermes Agents" in pg3.inner_text("#sidebar-nav"))
    pg3.screenshot(path=os.path.join(S, "admin_hermes.png"))
    b.close()
audit = asyncio.run(sql("SELECT detail->>'event' AS e FROM audit_trail WHERE action='console_session' ORDER BY id", fetch=True))
check("console sessions audited (start + end)", [a["e"] for a in audit][:2] == ["start", "end"], [a["e"] for a in audit])
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
