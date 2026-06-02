#!/bin/bash
# StaffBot.my — Gateway Entrypoint
# ===================================
# Starts the compatibility API that handles all client requests.
# Hermes is called as subprocess per-request with profile isolation.

set -e

echo "============================================"
echo "  StaffBot.my — Hermes Gateway v2"
echo "  API: 8080"
echo "============================================"

# ── 1. Bootstrap ──
mkdir -p /app/data/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home,profiles}

python3 /opt/staffbot/scripts/generate_gateway_config.py --output /app/data/config.yaml
cp /opt/staffbot/templates/gateway_soul.md /app/data/SOUL.md 2>/dev/null || true

# Sync profiles from DB
if [ -n "${DATABASE_URL:-}" ]; then
    python3 /opt/staffbot/scripts/profile_manager.py sync-all \
        --db-url "${DATABASE_URL}" --profiles-dir /app/data/profiles 2>&1 || true
fi

# ── 2. Start API ──
echo "[StaffBot] Starting API Gateway on :8080..."
cd /opt/staffbot
exec python3 -m uvicorn gateway_api:app --host 0.0.0.0 --port 8080
