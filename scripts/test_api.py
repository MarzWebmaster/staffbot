import httpx, json, asyncio

async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        # Login
        r = await c.post(
            "http://127.0.0.1:8000/api/v1/auth/login",
            json={"email": "marz@staffbot.my", "password": "Test1234"}
        )
        print("Login:", r.status_code)
        data = r.json()
        token = data.get("access_token", "")
        if not token:
            print("FAIL:", r.text[:200])
            return
        print("Token:", token[:20] + "...")

        # Check current config
        import subprocess
        print("\nBefore:")
        print(subprocess.check_output(["docker", "exec", "staffbot-gateway", "head", "-6", "/app/data/config.yaml"], text=True))

        # Update provider (triggers regenerate)
        auth = "Bearer " + token
        r = await c.put(
            "http://127.0.0.1:8000/api/v1/admin/llm/providers/5",
            json={"sort_order": 1},
            headers={"Authorization": auth}
        )
        print("Update:", r.status_code, r.text[:300])

        # Check config after
        print("\nAfter:")
        print(subprocess.check_output(["docker", "exec", "staffbot-gateway", "head", "-10", "/app/data/config.yaml"], text=True))

asyncio.run(main())
