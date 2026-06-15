import subprocess, time

def run(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
    if result.returncode != 0 and check:
        print(f"ERR: {result.stderr[:200]}")
    return result.stdout.strip()

print("=== 1. Recreate Gateway ===")
run("docker stop staffbot-gateway 2>/dev/null; docker rm staffbot-gateway 2>/dev/null")
out = run("docker run -d --name staffbot-gateway --network api_staffbot-network --restart unless-stopped -p 8080:8080 -p 8642:8642 -v /root/staffbot/profiles:/app/data/profiles -v /root/staffbot/containers:/root/staffbot/containers --env-file /root/staffbot/hermes-gateway/.env -e HERMES_HOME=/app/data -e STAFFBOT_PROFILES_DIR=/app/data/profiles staffbot-gateway:latest")
print(f"Gateway: {out[:20]}...")
time.sleep(4)

print("\n=== 2. Restart API ===")
run("cd /root/staffbot/api && docker compose up -d api")
time.sleep(4)

print("\n=== 3. Verify ===")
print("Gateway:", run("docker ps --format '{{.Status}}' --filter name=staffbot-gateway"))
print("API:", run("docker ps --format '{{.Status}}' --filter name=staffbot-api"))
print("Health 8080:", run("curl -s http://127.0.0.1:8080/health"))
print("Health 8000:", run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/"))

print("\n=== 4. Test Regenerate ===")
result = run("curl -s -X POST http://127.0.0.1:8080/admin/regenerate-config -H 'Content-Type: application/json' -H 'x-api-key: gw-staffbot-secure-key-2026' -d '{\"model\":{\"default\":\"test\"}}'")
print(result[:200])
