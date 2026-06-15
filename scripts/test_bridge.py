#!/usr/bin/env python3
"""Test LLM Provider Bridge end-to-end."""
import subprocess, json

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout.strip()

# Login
login = sh("curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{\"email\":\"marz@staffbot.my\",\"password\":\"Test1234\"}'")
data = json.loads(login)
token = data.get("access_token", "")
print("Token OK" if token else "Login FAILED")

# Current config
print("\n=== Current Config ===")
print(sh("docker exec staffbot-gateway head -6 /app/data/config.yaml"))

# Trigger provider update
print("\n=== Trigger Update ===")
auth = "Authorization: Bearer " + token
body = '{"sort_order": 1}'
result = sh(f"curl -s -X PUT http://127.0.0.1:8000/api/v1/admin/llm/providers/5 -H 'Content-Type: application/json' -H '{auth}' -d '{body}'")
print(result[:200])

# Config after
print("\n=== Config After ===")
print(sh("docker exec staffbot-gateway head -10 /app/data/config.yaml"))

# Hermes
print("\n=== Hermes :8642 ===")
print(sh("curl -s -o /dev/null -w 'HTTP %{http_code}' http://127.0.0.1:8642/"))
