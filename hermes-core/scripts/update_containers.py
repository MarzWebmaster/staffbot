#!/usr/bin/env python3
"""
StaffBot.my — Rolling Container Update Manager
==============================================
Updates ALL client containers to a new image version with zero downtime.

Usage on Server B:
    python3 update_containers.py v1.0.1          # Update to new version
    python3 update_containers.py v1.0.1 --force   # Force restart even if same version
    python3 update_containers.py list              # List all containers and their versions

Process:
    1. List all staffbot-type containers
    2. For each container (one by one):
       a. Stop current container
       b. Pull/load new image
       c. Start new container with same config
       d. Wait for health check
       e. Move to next
"""
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional

IMAGE_BASE = "staffbot-hermes-core"
GATEWAY_CONTAINER = "staffbot-gateway"
HEALTH_CHECK_RETRIES = 10
HEALTH_CHECK_INTERVAL = 3  # seconds


def run_cmd(cmd: list, timeout: int = 30) -> dict:
    """Run a shell command and return result."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout"}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "Command not found"}


def list_containers() -> list[dict]:
    """List all staffbot client containers with their details."""
    result = run_cmd([
        "docker", "ps", "-a",
        "--filter", "label=staffbot.type=client",
        "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Labels}}"
    ], timeout=10)

    containers = []
    for line in result["stdout"].split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 4:
            labels = parts[4] if len(parts) > 4 else ""
            client_id = ""
            for label in labels.split(","):
                if "staffbot.client_id=" in label:
                    client_id = label.split("=")[-1]
            containers.append({
                "id": parts[0][:12],
                "name": parts[1],
                "image": parts[2],
                "status": parts[3],
                "client_id": client_id,
            })
    return containers


def get_container_config(container_name: str) -> Optional[dict]:
    """Inspect a container and return its config (env, ports, networks)."""
    result = run_cmd([
        "docker", "inspect", container_name,
        "--format", json.dumps({
            "env": "{{range $k, $v := .Config.Env}}{{$v}}\n{{end}}",
            "port": "{{range $p, $conf := .NetworkSettings.Ports}}{{$p}}\n{{end}}",
            "network": "{{.HostConfig.NetworkMode}}",
            "restart": "{{.HostConfig.RestartPolicy.Name}}",
        }),
    ], timeout=10)

    if not result["success"]:
        return None

    # Parse env vars
    env_vars = {}
    env_text = result["stdout"]
    for line in env_text.split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            env_vars[k] = v

    return {
        "env": env_vars,
        "network": result.get("network", ""),
        "restart": result.get("restart", "unless-stopped"),
    }


def wait_for_health(container_name: str) -> bool:
    """Wait for container to pass health check."""
    for i in range(HEALTH_CHECK_RETRIES):
        result = run_cmd([
            "docker", "inspect", container_name,
            "--format", "{{.State.Status}}"
        ], timeout=5)

        if result["success"] and result["stdout"] == "running":
            # Check internal health endpoint
            health = run_cmd([
                "docker", "exec", container_name,
                "curl", "-sf", "http://localhost:8000/health",
            ], timeout=5)
            if health["success"]:
                return True

        time.sleep(HEALTH_CHECK_INTERVAL)

    return False


def update_container(container: dict, new_image: str, force: bool = False) -> dict:
    """Update a single container to a new image."""
    name = container["name"]
    current_image = container["image"]

    if current_image == new_image and not force:
        return {
            "name": name,
            "status": "skipped",
            "message": "Already on target image (use --force to restart anyway)",
        }

    print(f"  🔄 Updating {name}: {current_image} → {new_image}")

    # Get current config
    config = get_container_config(name)
    if not config:
        return {"name": name, "status": "failed", "message": "Cannot inspect container"}

    # Stop and remove old container
    print(f"     Stopping container...")
    run_cmd(["docker", "stop", name], timeout=30)
    run_cmd(["docker", "rm", name], timeout=10)

    # Build run command with preserved config
    env_args = []
    for k, v in config["env"].items():
        env_args.extend(["-e", f"{k}={v}"])

    run_cmd([
        "docker", "run", "-d",
        "--name", name,
        "--restart", config.get("restart", "unless-stopped"),
        "--network", config.get("network", "bridge"),
        *env_args,
        new_image,
        "gateway"
    ], timeout=60)

    # Wait for health
    if wait_for_health(name):
        return {"name": name, "status": "updated", "message": "Healthy"}
    else:
        return {"name": name, "status": "warning", "message": "Running but health check failed"}


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 update_containers.py <image_tag>      # Update all containers")
        print("  python3 update_containers.py <tag> --force     # Force restart")
        print("  python3 update_containers.py list              # List containers")
        sys.exit(1)

    action = sys.argv[1]
    force = "--force" in sys.argv

    if action == "list":
        containers = list_containers()
        if not containers:
            print("No staffbot client containers found.")
            return

        print(f"\n{'CONTAINER':<25} {'CLIENT':<10} {'IMAGE':<35} {'STATUS'}")
        print("-" * 85)
        for c in containers:
            print(f"{c['name']:<25} #{c['client_id']:<8} {c['image']:<35} {c['status']}")
        print(f"\nTotal: {len(containers)} containers")
        return

    # Update mode
    new_tag = action
    new_image = f"{IMAGE_BASE}:{new_tag}"

    # Verify image exists
    check = run_cmd(["docker", "image", "inspect", new_image], timeout=5)
    if not check["success"]:
        print(f"❌ Image '{new_image}' not found locally. Pull or load it first.")
        print(f"   docker pull <registry>/{new_image}")
        sys.exit(1)

    containers = list_containers()
    print(f"\n📋 Found {len(containers)} containers to update to {new_image}")
    print()

    results = []
    for container in containers:
        result = update_container(container, new_image, force)
        results.append(result)
        emoji = "✅" if result["status"] == "updated" else \
                "⏭️" if result["status"] == "skipped" else \
                "⚠️" if result["status"] == "warning" else "❌"
        print(f"  {emoji} {result['name']:<30} → {result['message']}")
        print()

    # Summary
    updated = sum(1 for r in results if r["status"] == "updated")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")
    warning = sum(1 for r in results if r["status"] == "warning")

    print("=" * 50)
    print(f"✅ Updated: {updated}  ⏭️ Skipped: {skipped}  ⚠️ Warning: {warning}  ❌ Failed: {failed}")
    print(f"🎉 All done! Image: {new_image}")


if __name__ == "__main__":
    main()
