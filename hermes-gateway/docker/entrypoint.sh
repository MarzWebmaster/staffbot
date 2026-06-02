#!/bin/bash
# StaffBot.my — Hermes Gateway Entrypoint
# ========================================
# Runs BEFORE Hermes gateway to:
#   1. Ensure Hermes config is set up
#   2. Sync client profiles from DB
#   3. Configure messaging platforms (Telegram, WhatsApp/Baileys)
#   4. Start Hermes gateway with StaffBot middleware
#
# Env vars expected:
#   DATABASE_URL    — PostgreSQL connection for client configs
#   HERMES_HOME     — Hermes data directory
#   STAFFBOT_SCRIPTS— Path to StaffBot scripts

set -e

HERMES_HOME="${HERMES_HOME:-/app/data}"
INSTALL_DIR="/opt/hermes-agent"
STAFFBOT_SCRIPTS="${STAFFBOT_SCRIPTS:-/opt/staffbot/scripts}"
STAFFBOT_TEMPLATES="${STAFFBOT_TEMPLATES:-/opt/staffbot/templates}"
STAFFBOT_PROFILES_DIR="${STAFFBOT_PROFILES_DIR:-/app/data/profiles}"

echo "============================================"
echo "  StaffBot.my — Hermes Gateway"
echo "  Multi-Tenant Central Brain"
echo "============================================"

# ── 1. Bootstrap Hermes config ─────────────────────────────────────────
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home,profiles}

# Generate base config.yaml if not exists
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    echo "[StaffBot] Generating base Hermes config..."
    python3 "$STAFFBOT_SCRIPTS/generate_gateway_config.py" \
        --output "$HERMES_HOME/config.yaml"
    echo "[StaffBot] ✅ Base config.yaml created"
fi

# Copy .env if not exists
if [ ! -f "$HERMES_HOME/.env" ]; then
    echo "[StaffBot] Creating .env..."
    cat > "$HERMES_HOME/.env" << 'ENVEOF'
# StaffBot.my — Hermes Gateway Environment
# Managed keys are injected at runtime per-client profile.
# BYOK keys are stored in per-profile .env files.
ENVEOF
    echo "[StaffBot] ✅ .env created"
fi

# ── 2. Sync client profiles from DB ────────────────────────────────────
echo "[StaffBot] Syncing client profiles from database..."
if [ -n "${DATABASE_URL:-}" ]; then
    python3 "$STAFFBOT_SCRIPTS/profile_manager.py" sync-all \
        --db-url "${DATABASE_URL}" \
        --profiles-dir "$STAFFBOT_PROFILES_DIR" \
        2>&1 || echo "[StaffBot] ⚠️  Profile sync had warnings (will retry)"
else
    echo "[StaffBot] ⚠️  No DATABASE_URL set — skipping profile sync"
fi

# ── 3. Load StaffBot soul ──────────────────────────────────────────────
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp "$STAFFBOT_TEMPLATES/gateway_soul.md" "$HERMES_HOME/SOUL.md" 2>/dev/null || true
    echo "[StaffBot] ✅ Default gateway SOUL.md created"
fi

# ── 4. Sync bundled skills ─────────────────────────────────────────────
if [ -d "$INSTALL_DIR/skills" ]; then
    echo "[StaffBot] Syncing bundled skills..."
    python3 "$INSTALL_DIR/tools/skills_sync.py" 2>/dev/null || true
fi

# ── 5. Run Hermes Gateway ──────────────────────────────────────────────
echo "[StaffBot] 🚀 Starting Hermes Gateway..."
echo "[StaffBot]    Profiles dir: $STAFFBOT_PROFILES_DIR"
echo "[StaffBot]    Data dir: $HERMES_HOME"

exec hermes "$@"
