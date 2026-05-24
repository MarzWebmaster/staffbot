#!/bin/bash
# StaffBot.my — Extended entrypoint for per-client Hermes containers
# ===================================================================
# Runs BEFORE the official Hermes entrypoint to:
#   1. Inject client soul config from pgvector -> SOUL.md + config.yaml
#   2. Filter skills/tools based on PACKAGE level
#   3. Configure managed LLM provider
#   4. Then delegates to the official entrypoint
#
# Env vars expected:
#   CLIENT_ID       (required) — Integer ID of the client
#   PACKAGE         (optional, default: "basic") — basic | pro | enterprise
#   MEMORY_DB_URL   (optional) — pgvector connection string
#   MANAGED_LLM_KEY (optional) — API key if using managed LLM (Tier 2)
#   LLM_API_KEY     (optional) — BYOK if client brings their own
#   STAFFBOT_MODE   (optional) — "gateway" (default) | "chat"

set -e

HERMES_HOME="${HERMES_HOME:-/app/data}"
INSTALL_DIR="/opt/hermes-agent"
STAFFBOT_SCRIPTS="${STAFFBOT_SCRIPTS:-/opt/staffbot/scripts}"
STAFFBOT_TEMPLATES="${STAFFBOT_TEMPLATES:-/opt/staffbot/templates}"

# ── 1. Bootstrap config files (official setup) ────────────────────────
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# Copy .env if not exists
if [ ! -f "$HERMES_HOME/.env" ]; then
    if [ -f "$INSTALL_DIR/.env.example" ]; then
        cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"
    else
        touch "$HERMES_HOME/.env"
    fi
fi

# Skip if no CLIENT_ID (running in dev/test mode without StaffBot)
if [ -z "${CLIENT_ID:-}" ] || [ "$CLIENT_ID" = "0" ]; then
    echo "[StaffBot] No CLIENT_ID set — skipping StaffBot injection, running plain Hermes"
    exec hermes "$@"
fi

echo "============================================"
echo "  StaffBot.my — Client #${CLIENT_ID}"
echo "  Package: ${PACKAGE:-basic}"
echo "============================================"

# ── 2. Generate config.yaml ────────────────────────────────────────────
# This merges the template with package-specific settings + governance policy
CLIENT_CONFIG_PATH="/root/staffbot/containers/client_${CLIENT_ID}.json"
python3 "$STAFFBOT_SCRIPTS/generate_config.py" \
    --client-id "${CLIENT_ID}" \
    --package "${PACKAGE:-basic}" \
    --client-config "${CLIENT_CONFIG_PATH}" \
    --output "$HERMES_HOME/config.yaml"

echo "[StaffBot] ✅ config.yaml generated (package: ${PACKAGE:-basic})"

# ── 3. Inject client soul from pgvector ────────────────────────────────
# If MEMORY_DB_URL is set, load the client's soul config from pgvector
if [ -n "${MEMORY_DB_URL:-}" ]; then
    python3 "$STAFFBOT_SCRIPTS/load_soul.py" \
        --client-id "${CLIENT_ID}" \
        --memory-db-url "${MEMORY_DB_URL}" \
        --output "$HERMES_HOME/SOUL.md"
    echo "[StaffBot] ✅ Soul loaded from pgvector"
fi

# If no SOUL.md yet (first run, DB not ready), use a default
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp "$STAFFBOT_TEMPLATES/default_soul.md" "$HERMES_HOME/SOUL.md" 2>/dev/null || true
    echo "[StaffBot] ⚠️  Default SOUL.md used (no pgvector soul found)"
fi

# ── 4. Configure LLM ──────────────────────────────────────────────────
# Managed LLM (Tier 2) vs BYOK (Tier 1)
if [ -n "${MANAGED_LLM_KEY:-}" ]; then
    # Inject managed LLM key into .env
    if ! grep -q "OPENROUTER_API_KEY" "$HERMES_HOME/.env" 2>/dev/null; then
        echo "OPENROUTER_API_KEY=${MANAGED_LLM_KEY}" >> "$HERMES_HOME/.env"
        echo "[StaffBot] ✅ Managed LLM configured (StaffBot-provided)"
    fi
elif [ -n "${LLM_API_KEY:-}" ]; then
    if ! grep -q "OPENROUTER_API_KEY" "$HERMES_HOME/.env" 2>/dev/null; then
        echo "OPENROUTER_API_KEY=${LLM_API_KEY}" >> "$HERMES_HOME/.env"
        echo "[StaffBot] ✅ BYOK LLM configured (client-provided)"
    fi
else
    echo "[StaffBot] ⚠️  No LLM API key configured!"
fi

# ── 5. Sync skills ────────────────────────────────────────────────────
# The official entrypoint syncs built-in skills.
# Our package filtering was already applied in generate_config.py
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py" 2>/dev/null || true
fi

# ── 6. Run Hermes directly (no official entrypoint needed) ──────────
# Skip the official entrypoint (gosu/chown fails in read-only no-new-privileges containers).
# Our StaffBot entrypoint already handles all setup.
echo "[StaffBot] 🚀 Running Hermes Agent..."
export HERMES_HOME="${HERMES_HOME:-/app/data}"
exec hermes "$@"
