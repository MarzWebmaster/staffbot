"""
Patch gateway_api.py — add client profile update endpoint
"""
with open("/root/staffbot/hermes-gateway/gateway_api.py") as f:
    gw = f.read()

new_endpoint = """
@app.patch("/admin/client-profile/{client_id}")
async def update_client_profile(client_id: int, updates: dict, x_api_key: str = Header(None, alias="x-api-key")):
    \"\"\"Update a specific client's profile config (rate limits, quota).\"\"\"
    if x_api_key != GATEWAY_AUTH:
        raise HTTPException(status_code=401)
    profile_dir = os.path.join(PROFILES_DIR, f"client_{client_id}")
    config_path = os.path.join(profile_dir, "config.yaml")
    if not os.path.exists(config_path):
        return {"success": False, "error": "profile_not_found"}
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        # Deep merge updates
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        return {"success": True, "client_id": client_id, "updated": list(updates.keys())}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

"""

# Insert before the regenerate-config endpoint
marker = '@app.post("/admin/regenerate-config")'
if marker in gw:
    gw = gw.replace(marker, new_endpoint + marker)
    with open("/root/staffbot/hermes-gateway/gateway_api.py", "w") as f:
        f.write(gw)
    print("OK" if "client-profile" in open("/root/staffbot/hermes-gateway/gateway_api.py").read() else "FAIL")
else:
    print("FAIL: marker not found")
