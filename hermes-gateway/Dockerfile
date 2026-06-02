# StaffBot.my — Hermes Gateway (Multi-Tenant Central Brain)
# ============================================================
# Runs Hermes Agent in gateway mode, serving ALL clients from ONE container.
# Each client gets a Hermes profile with full isolation.
#
# Build:
#   docker build -t staffbot-hermes-gateway:latest .
#
# Run:
#   docker run -d --name staffbot-hermes-gateway \
#     --network staffbot-network \
#     -p 8080:8080 -p 8653:8653 -p 8654:8654 \
#     -v /root/staffbot/profiles:/app/data/profiles \
#     -v /root/staffbot/containers:/root/staffbot/containers \
#     -e DATABASE_URL=postgresql://staffbot:***@staffbot-db:5432/staffbot_db \
#     -e HERMES_HOME=/app/data \
#     staffbot-hermes-gateway:latest

FROM python:3.11-slim

LABEL maintainer="StaffBot.my <support@staffbot.my>"
LABEL staffbot.type="hermes-gateway"
LABEL description="StaffBot.my — Multi-tenant Hermes Gateway (shared central brain)"

# ── System dependencies ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Create hermes user/group ───────────────────────────────────────────
RUN groupadd -g 10000 hermes && \
    useradd -u 10000 -g hermes -m -d /home/hermes -s /bin/bash hermes

# ── Install Hermes Agent from GitHub source ────────────────────────────
WORKDIR /opt
RUN git clone --depth 1 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent && \
    cd /opt/hermes-agent && \
    pip install --no-cache-dir -e .

RUN ln -s /opt/hermes-agent /opt/hermes

# ── Create venv ────────────────────────────────────────────────────────
RUN python3 -m venv /opt/hermes/.venv && \
    /opt/hermes/.venv/bin/pip install --no-cache-dir -e /opt/hermes-agent

# ── StaffBot-specific dependencies ─────────────────────────────────────
RUN pip install --no-cache-dir \
    asyncpg \
    psycopg2-binary \
    pyyaml \
    docker \
    fastapi uvicorn

# ── Copy StaffBot scripts ──────────────────────────────────────────────
COPY scripts/ /opt/staffbot/scripts/
COPY templates/ /opt/staffbot/templates/
COPY docker/ /opt/staffbot/docker/
COPY gateway_api.py /opt/staffbot/gateway_api.py
RUN chmod +x /opt/staffbot/scripts/*.py /opt/staffbot/scripts/*.sh 2>/dev/null || true
RUN chmod +x /opt/staffbot/docker/*.sh 2>/dev/null || true

# ── Supervisor entrypoint ───────────────────────────────────────────────
COPY supervisor-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Environment ────────────────────────────────────────────────────────
ENV HERMES_HOME=/app/data
ENV STAFFBOT_SCRIPTS=/opt/staffbot/scripts
ENV STAFFBOT_TEMPLATES=/opt/staffbot/templates
ENV STAFFBOT_PROFILES_DIR=/app/data/profiles

# ── Prepare directories ────────────────────────────────────────────────
RUN mkdir -p /app/data/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home,profiles}

# ── Expose ports ───────────────────────────────────────────────────────
EXPOSE 8080 8653 8654

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gateway"]
