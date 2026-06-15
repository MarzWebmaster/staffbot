"""
Patch llm_providers.py — replace _notify_gateway_regenerate with full config push.
"""
with open("/root/staffbot/api/app/routers/admin/llm_providers.py") as f:
    content = f.read()

old_func = '''async def _notify_gateway_regenerate():
    """Notify gateway to regenerate config from DB."""
    import httpx, os
    gw_url = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://staffbot-gateway:8080")
    gw_key = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{gw_url}/admin/regenerate-config",
                headers={"x-api-key": gw_key},
            )
    except Exception:
        pass  # Silent fail — gateway will pick up on restart'''

new_func = '''async def _notify_gateway_regenerate(db):
    """Build Hermes config from DB providers and push to gateway."""
    from app.services.gateway_config_service import build_gateway_config, push_config_to_gateway
    try:
        config = await build_gateway_config(db)
        await push_config_to_gateway(config)
    except Exception:
        pass  # Silent fail — gateway will pick up on restart'''

content = content.replace(old_func, new_func)

# Update calls: await _notify_gateway_regenerate() → await _notify_gateway_regenerate(db)
content = content.replace(
    "await _notify_gateway_regenerate()\n    return",
    "await _notify_gateway_regenerate(db)\n    return"
)
# Handle the delete case (different return format)
content = content.replace(
    "await _notify_gateway_regenerate()\n    return {\"message\"",
    "await _notify_gateway_regenerate(db)\n    return {\"message\""
)

with open("/root/staffbot/api/app/routers/admin/llm_providers.py", "w") as f:
    f.write(content)

print("OK" if "build_gateway_config" in open("/root/staffbot/api/app/routers/admin/llm_providers.py").read() else "FAIL")
