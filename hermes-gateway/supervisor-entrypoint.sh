#!/bin/bash
# StaffBot.my — Hybrid Gateway Entrypoint v3
# ===========================================
# Runs BOTH:
#   1. Hermes Native Gateway on :8642 (OpenAI-compatible API + plugins + sessions)
#   2. StaffBot Custom API on :8080 (legacy compat — tool calling, tasks, upload)
#
# Migration path: clients move from :8080 → :8642

set -e

echo "============================================"
echo "  StaffBot.my — Hybrid Gateway v3"
echo "  Hermes Native :8642"
echo "  Custom API    :8080"
echo "============================================"

# ── Bootstrap ──
mkdir -p /app/data/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home,profiles}

python3 /opt/staffbot/scripts/generate_gateway_config.py --output /app/data/config.yaml
cp /opt/staffbot/templates/gateway_soul.md /app/data/SOUL.md 2>/dev/null || true

# Sync profiles from DB
if [ -n "${DATABASE_URL:-}" ]; then
    python3 /opt/staffbot/scripts/profile_manager.py sync-all \
        --db-url "${DATABASE_URL}" --profiles-dir /app/data/profiles 2>&1 || true
fi

# ── 1. Start Hermes Native Gateway (background) ──
echo "[StaffBot] Starting Hermes Native Gateway on :8642..."
export HERMES_HOME=/app/data
hermes gateway run --accept-hooks &
HERMES_PID=$!
echo "[StaffBot] Hermes PID: $HERMES_PID"

# Wait for Hermes to be ready
for i in $(seq 1 20); do
    if curl -s http://localhost:8642/health > /dev/null 2>&1; then
        echo "[StaffBot] Hermes Native ready on :8642"
        break
    fi
    sleep 1
done

# ── 2. Start StaffBot Custom API (foreground) ──
echo "[StaffBot] Starting Custom API on :8080..."
cd /opt/staffbot
exec python3 -m uvicorn gateway_api:app --host 0.0.0.0 --port 8080
