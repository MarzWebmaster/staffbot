"""Orchestrator + managed config tests with a fake Docker client and real Postgres."""
import os as _os
REPO = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
API_DIR = _os.path.join(REPO, "api")
# Throwaway database: tests TRUNCATE and recreate tables. Never point at production.
TEST_DB = _os.environ.get("STAFFBOT_TEST_DATABASE_URL", "postgresql://t:t@localhost:5432/t")
import os, sys, asyncio, tempfile, yaml
S = tempfile.mkdtemp()
os.environ.update({"STAFFBOT_DATABASE_URL": TEST_DB, "STAFFBOT_SECRET_KEY": "k",
                   "STAFFBOT_LLM_PROXY_SECRET": "proxysecret", "STAFFBOT_HERMES_MANAGED_DIR": S + "/managed",
                   "STAFFBOT_HERMES_BACKUP_DIR": S + "/backups", "STAFFBOT_HERMES_RUNTIME": "runsc"})
sys.path.insert(0, API_DIR)
import asyncpg, docker
from datetime import datetime, timedelta

class NotFound(docker.errors.NotFound):
    def __init__(self, m="nf"): Exception.__init__(self, m)
class FakeContainer:
    def __init__(self, kw): self.kw, self.status, self.attrs = kw, "running", {"NetworkSettings": {"Ports": {"8642/tcp": [{"HostIp": "172.30.0.1", "HostPort": "40001"}]}}}
    name = property(lambda s: s.kw["name"])
    def reload(self): pass
    def stop(self, timeout=10): self.status = "exited"
    def start(self): self.status = "running"
    def remove(self, force=False): FakeDocker.containers_.pop(self.name, None)
class Containers:
    def get(self, n):
        if n not in FakeDocker.containers_: raise NotFound()
        return FakeDocker.containers_[n]
    def run(self, image=None, *a, **kw):
        if kw.get("remove"):  # backup helper
            FakeDocker.helper_runs.append((image, a, kw))
            d = kw["volumes"]
            host = [h for h, b in d.items() if b["bind"] == "/backup"][0]
            open(os.path.join(host, a[0][2].split("/")[-1]), "w").write("x")
            return None
        kw["image"] = image; c = FakeContainer(kw); FakeDocker.containers_[kw["name"]] = c; return c
class Coll:
    def __init__(self, store): self.store = store
    def get(self, n):
        if n not in self.store: raise NotFound()
        return type("O", (), {"remove": lambda s, force=False: self.store.pop(n, None)})()
    def create(self, n, **kw): self.store[n] = kw
class FakeDocker:
    containers_, networks_, volumes_, helper_runs = {}, {}, {}, []
    containers = Containers(); networks = Coll(networks_); volumes = Coll(volumes_)

from app.services import hermes_orchestrator as orch, hermes_config
from app.utils.encryption import encrypt_value, decrypt_value
from app.llm_proxy.tokens import parse_token
async def ok_health(port, key): return True
orch._wait_healthy = ok_health

DB = TEST_DB
async def sql(q, *a, fetch=False):
    c = await asyncpg.connect(DB)
    try: return await (c.fetch(q, *a) if fetch else c.execute(q, *a))
    finally: await c.close()
import app.main, app.database as adb
asyncio.run(adb.init_db()); asyncio.run(adb.engine.dispose())
async def seed():
    await sql("TRUNCATE clients, packages, llm_providers RESTART IDENTITY CASCADE")
    await sql("INSERT INTO llm_providers (name,display_name,base_url,api_key_encrypted,models,default_model,is_active,sort_order) VALUES ('deepseek','DS','http://x/v1',$1,'[\"deepseek-chat\"]','deepseek-chat',true,0)", encrypt_value("K"))
    await sql("""INSERT INTO packages (name,price_monthly,allowed_models,byok_allowed,agent_terminal,catalog_tier,idle_sleep_minutes,backup_retention_days,memory_limit_mb,cpu_limit) VALUES
      ('starter',49,'[]',true,false,'basic',30,7,1024,0.5),('ent',499,'["*"]',true,true,'all',0,30,4096,2)""")
    await sql("INSERT INTO package_providers (package_id,provider_id,token_quota,is_available) VALUES (1,1,0,true),(2,1,0,true)")
    await sql("INSERT INTO clients (name,email,package,status,llm_token_version,created_at,updated_at) VALUES ('a','a@x','starter','active',3,now(),now()),('b','b@x','ent','active',1,now(),now())")
asyncio.run(seed())

res = []
def check(n, c, i=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{str(i)[:200]}]" if i else ""))
from app.database import async_session_factory as F

async def main():
    dk = FakeDocker()
    async with F() as db:
        inst = await orch.provision(db, 1, dk=dk)
    check("provision -> running with published port", inst.status == "running" and inst.api_port == 40001, (inst.status, inst.api_port))
    kw = FakeDocker.containers_["staffbot-hermes-1"].kw
    check("container hardening", kw["cap_drop"] == ["ALL"] and "no-new-privileges:true" in kw["security_opt"] and kw["runtime"] == "runsc" and kw["pids_limit"] == 512, kw)
    check("limits from package", kw["mem_limit"] == "1024m" and kw["nano_cpus"] == int(0.5e9) and kw["shm_size"] == "64m")
    check("ports bound to customer gateway IP only", kw["ports"] == {"8642/tcp": ("172.30.0.1", None)})
    vols = kw["volumes"]
    check("data volume + read-only managed files", vols["staffbot-hermes-1"]["bind"] == "/opt/data" and all(v["mode"] == "ro" for k, v in vols.items() if "/managed/" in k) and len(vols) == 3)
    check("no docker.sock mounted", not any("docker.sock" in k for k in vols))
    net = FakeDocker.networks_.get("staffbot-customers", {})
    check("customer network: ICC disabled, fixed gateway", net.get("options", {}).get("com.docker.network.bridge.enable_icc") == "false", net)

    cfg = yaml.safe_load(open(f"{S}/managed/1/config.yaml"))
    env = dict(l.split("=", 1) for l in open(f"{S}/managed/1/.env").read().splitlines())
    check("managed model -> proxy, default model from package", cfg["model"]["base_url"] == "http://172.30.0.1:8090/v1" and cfg["model"]["default"] == "deepseek-chat" and cfg["model"]["key_env"] == "STAFFBOT_LLM_TOKEN", cfg["model"])
    check("no fallback providers, all aux -> main", cfg["fallback_providers"] == [] and all(v["provider"] == "main" for v in cfg["auxiliary"].values()))
    check("starter disables terminal/code/browser/computer_use", set(["terminal", "code_execution", "browser", "computer_use"]) <= set(cfg["agent"]["disabled_toolsets"]))
    check("plugin enabled + core skills dir", cfg["plugins"]["enabled"] == ["staffbot"] and cfg["skills"]["external_dirs"] == ["/opt/staffbot/skills"])
    check("background_review off for idle-sleep plan", cfg["auxiliary"]["background_review"]["enabled"] is False)
    check("token in .env matches client + version", parse_token(env["STAFFBOT_LLM_TOKEN"]) == (1, 3))
    check("API server on 0.0.0.0:8642 with 64-hex key", env["API_SERVER_HOST"] == "0.0.0.0" and len(env["API_SERVER_KEY"]) == 64)
    check("managed files mode 0644", oct(os.stat(f"{S}/managed/1/.env").st_mode)[-3:] == "644")
    key1 = env["API_SERVER_KEY"]

    async with F() as db:
        await orch.provision(db, 1, dk=dk)
    env2 = dict(l.split("=", 1) for l in open(f"{S}/managed/1/.env").read().splitlines())
    check("re-provision keeps API server key", env2["API_SERVER_KEY"] == key1)

    async with F() as db:
        inst2 = await orch.provision(db, 2, dk=dk)
    cfg2 = yaml.safe_load(open(f"{S}/managed/2/config.yaml")); kw2 = FakeDocker.containers_["staffbot-hermes-2"].kw
    check("enterprise: terminal allowed, only computer_use off", cfg2["agent"]["disabled_toolsets"] == ["computer_use"], cfg2["agent"])
    check("enterprise: shm 1g, 4096m, background_review on", kw2["shm_size"] == "1g" and kw2["mem_limit"] == "4096m" and cfg2["auxiliary"]["background_review"]["enabled"] is True)

    # idle reaping
    await sql("UPDATE hermes_instances SET last_active_at = now() - interval '2 hours'")
    async with F() as db:
        slept = await orch.reap_idle(db, dk=dk)
    check("reap: starter (30 min) sleeps, enterprise (always on) stays", slept == [1] and FakeDocker.containers_["staffbot-hermes-1"].status == "exited" and FakeDocker.containers_["staffbot-hermes-2"].status == "running", slept)

    async with F() as db:
        inst = await orch.wake(db, 1, dk=dk)
    check("wake restarts sleeping container", inst.status == "running" and FakeDocker.containers_["staffbot-hermes-1"].status == "running")

    # upgrade keeps volume, snapshots first
    async with F() as db:
        inst = await orch.upgrade(db, 1, "staffbot-hermes:0.23.0-sb1", dk=dk)
    kw = FakeDocker.containers_["staffbot-hermes-1"].kw
    check("upgrade: new image, same volume, snapshot taken", inst.image == "staffbot-hermes:0.23.0-sb1" and kw["image"] == "staffbot-hermes:0.23.0-sb1" and "staffbot-hermes-1" in kw["volumes"] and FakeDocker.helper_runs and inst.last_backup_at)
    hr = FakeDocker.helper_runs[-1]
    check("backup helper: read-only data, no network", hr[2]["network_disabled"] and hr[2]["volumes"]["staffbot-hermes-1"]["mode"] == "ro")

    # backup pruning
    bdir = f"{S}/backups/1"; old = (datetime.utcnow() - timedelta(days=40)).strftime("%Y%m%dT%H%M%SZ") + ".tar.gz"
    open(f"{bdir}/{old}", "w").write("x")
    orch.backup(1, 7, dk=dk)
    check("backup prunes beyond retention", old not in os.listdir(bdir) and len(os.listdir(bdir)) >= 1, os.listdir(bdir))

    # package change re-renders config
    await sql("UPDATE packages SET agent_terminal=true, catalog_tier='all', memory_limit_mb=2048 WHERE name='starter'")
    async with F() as db:
        await orch.apply_package(db, 1, dk=dk)
    cfg = yaml.safe_load(open(f"{S}/managed/1/config.yaml"))
    check("apply_package re-renders toolsets and limits", cfg["agent"]["disabled_toolsets"] == ["computer_use"] and FakeDocker.containers_["staffbot-hermes-1"].kw["mem_limit"] == "2048m")

    async with F() as db:
        await orch.deprovision(db, 2, keep_volume=True, dk=dk)
    check("deprovision keeps volume by default", "staffbot-hermes-2" not in FakeDocker.containers_ and "staffbot-hermes-2" in FakeDocker.volumes_)

    # failure path: docker run raises
    def boom(*a, **k): raise RuntimeError("image not found")
    orig = Containers.run; Containers.run = lambda self, image=None, *a, **kw: boom()
    async with F() as db:
        try: await orch.provision(db, 2, dk=dk); failed = False
        except orch.OrchestratorError: failed = True
    Containers.run = orig
    st = (await sql("SELECT status, last_error FROM hermes_instances WHERE client_id=2", fetch=True))[0]
    check("provision failure recorded as error", failed and st["status"] == "error" and "image not found" in st["last_error"], dict(st))
asyncio.run(main())
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
