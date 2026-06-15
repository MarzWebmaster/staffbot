#!/usr/bin/env python3
"""Add SECRET_KEY to gateway docker-compose env."""
import subprocess

secret = subprocess.check_output(
    ["docker", "exec", "staffbot-api", "python3", "-c",
     "from app.config import get_settings; print(get_settings().SECRET_KEY)"],
    timeout=10
).decode().strip()

print(f"SECRET_KEY: {secret[:12]}...")

with open("/root/staffbot/api/docker-compose.yml") as f:
    dc = f.read()

if "SECRET_KEY" not in dc:
    old = "      - MIMO_KEY=sk-jem...prod\n"
    new = "      - MIMO_KEY=sk-jem...prod\n      - SECRET_KEY=" + secret + "\n"
    dc = dc.replace(old, new)
    with open("/root/staffbot/api/docker-compose.yml", "w") as f:
        f.write(dc)
    print("Added SECRET_KEY to docker-compose")
else:
    print("SECRET_KEY already exists")

# Verify
subprocess.run(["grep", "SECRET_KEY", "/root/staffbot/api/docker-compose.yml"])
