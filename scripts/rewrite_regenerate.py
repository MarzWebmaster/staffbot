with open("/root/staffbot/hermes-gateway/gateway_api.py") as f:
    gw = f.read()

# Find the regenerate-config endpoint and rewrite it
old_marker = '@app.post("/admin/regenerate-config")'
end_marker = '@app.put("/admin/reload-profile/batch")'

old_start = gw.find(old_marker)
old_end = gw.find(end_marker)

if old_start >= 0 and old_end > old_start:
    new_endpoint = '''@app.post("/admin/regenerate-config")
async def regenerate_config(config: dict, x_api_key: str = Header(None, alias="x-api-key")):
    """Receive config from API and apply it + reload Hermes."""
    if x_api_key != GATEWAY_AUTH:
        raise HTTPException(status_code=401)
    import os as _os, signal as _signal
    try:
        _os.makedirs(_os.path.dirname("/app/data/config.yaml") or ".", exist_ok=True)
        with open("/app/data/config.yaml", "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        # SIGHUP Hermes server
        for pid in _os.listdir("/proc"):
            if pid.isdigit():
                try:
                    with open(f"/proc/{pid}/cmdline") as pf:
                        cmd = pf.read()
                    if "hermes" in cmd and "server" in cmd:
                        _os.kill(int(pid), _signal.SIGHUP)
                        break
                except:
                    pass
        return {"success": True, "message": "Config applied and Hermes reloaded"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

'''

    gw = gw[:old_start] + new_endpoint + gw[old_end:]
    with open("/root/staffbot/hermes-gateway/gateway_api.py", "w") as f:
        f.write(gw)
    print("OK")
else:
    print(f"FAIL: old_start={old_start}, old_end={old_end}")
