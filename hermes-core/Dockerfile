# StaffBot.my — Hermes Core Image
# ================================
# Installs Hermes Agent from source + StaffBot customizations:
#   - Soul injection from pgvector (per-client personality)
#   - Package-based skill filtering (basic/pro/enterprise)
#   - Client-specific config.yaml generation
#   - Managed LLM support (no BYOK needed)
#
# Build:
#   docker build -t staffbot-hermes-core:v1.0.0 .
#
# Run (example):
#   docker run -d \
#     --name staffbot-client-1 \
#     -e CLIENT_ID=1 \
#     -e PACKAGE=pro \
#     -e STAFFBOT_LLM_KEY=sk-... \
#     staffbot-hermes-core:v1.0.0

FROM python:3.11-slim

LABEL maintainer="StaffBot.my <support@staffbot.my>"
LABEL staffbot.type="client-container"
LABEL description="StaffBot.my — Per-client Hermes Agent container with soul injection"

# ── System dependencies ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# ── Create hermes user/group (required by official entrypoint) ────────
RUN groupadd -g 10000 hermes && \
    useradd -u 10000 -g hermes -m -d /home/hermes -s /bin/bash hermes

# ── Install Hermes Agent from GitHub source ────────────────────────────
# Clone with depth=1 for minimal size, install in editable mode
WORKDIR /opt
RUN git clone --depth 1 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent && \
    cd /opt/hermes-agent && \
    pip install --no-cache-dir -e .

# ── Symlink for official entrypoint compatibility ─────────────────────
# Official docker/entrypoint.sh hardcodes INSTALL_DIR="/opt/hermes"
RUN ln -s /opt/hermes-agent /opt/hermes

# ── Create venv (required by official entrypoint) ─────────────────────
# Official entrypoint activates /opt/hermes/.venv before running Hermes
RUN python3 -m venv /opt/hermes/.venv && \
    /opt/hermes/.venv/bin/pip install --no-cache-dir -e /opt/hermes-agent

# ── Verify Hermes installation ─────────────────────────────────────────
RUN hermes --version && \
    python3 -c "import hermes; print(f'Hermes OK: {hermes.__file__}')" 2>/dev/null || true

# ── Install StaffBot-specific dependencies ────────────────────────────
RUN pip install --no-cache-dir \
    asyncpg \
    psycopg2-binary \
    pyyaml

# ── Copy StaffBot scripts ─────────────────────────────────────────────
COPY scripts/ /opt/staffbot/scripts/
COPY templates/ /opt/staffbot/templates/
RUN chmod +x /opt/staffbot/scripts/*.py

# ── StaffBot entrypoint ───────────────────────────────────────────────
# Our script runs BEFORE the final `exec hermes "$@"` to:
#   1. Load soul from pgvector -> generate config.yaml + SOUL.md
#   2. Filter skills based on PACKAGE env var
#   3. Set up managed LLM if applicable
COPY docker/staffbot-entrypoint.sh /opt/hermes-agent/docker/staffbot-entrypoint.sh
RUN chmod +x /opt/hermes-agent/docker/staffbot-entrypoint.sh

ENV STAFFBOT_HOME=/app/data
ENV STAFFBOT_SCRIPTS=/opt/staffbot/scripts
ENV STAFFBOT_TEMPLATES=/opt/staffbot/templates

# Prepare Hermes home directories
RUN mkdir -p /app/data/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# Default: run Hermes in headless gateway mode
# Override by passing different CMD (e.g., "chat -q 'hello'")
ENTRYPOINT ["/opt/hermes-agent/docker/staffbot-entrypoint.sh"]
CMD ["gateway"]
