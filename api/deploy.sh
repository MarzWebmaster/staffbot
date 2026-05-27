#!/usr/bin/env bash
# StaffBot.my API Backend — Deployment Script for Server A
# Usage: bash deploy.sh [env_file]
#
# Steps:
# 1. Copy .env file
# 2. Build and start Docker containers
# 3. Run database migrations
# 4. Check health

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="${1:-.env}"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  StaffBot.my API Backend — Deploy      ${NC}"
echo -e "${YELLOW}========================================${NC}"

# 1. Check .env file
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: $ENV_FILE not found.${NC}"
    echo "Copy from .env.example: cp .env.example .env"
    exit 1
fi
echo -e "${GREEN}[1/5]✓ .env file found${NC}"

# 2. Export env vars and check SECRET_KEY
export $(grep -v '^#' "$ENV_FILE" | xargs)
if [ "${SECRET_KEY:-}" = "change-me-to-a-random-64-char-string" ] || [ -z "${SECRET_KEY:-}" ]; then
    echo -e "${RED}Error: SECRET_KEY must be changed from default.${NC}"
    echo "Generate one: python3 -c 'import secrets; print(secrets.token_urlsafe(64))'"
    exit 1
fi
echo -e "${GREEN}[2/5]✓ Secret key validated${NC}"

# 3. Build and start containers
echo "Building Docker images..."
docker compose build --quiet
echo -e "${GREEN}[3/5]✓ Docker images built${NC}"

echo "Starting containers..."
docker compose up -d
echo -e "${GREEN}[4/5]✓ Containers started${NC}"

# 4. Health check
echo "Waiting for API to be ready..."
for i in {1..30}; do
    if curl -s -f http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo -e "${GREEN}[5/5]✓ API is healthy!${NC}"
        echo ""
        echo -e "${YELLOW}========================================${NC}"
        echo -e "${GREEN}  Deployment Complete!${NC}"
        echo -e "${YELLOW}========================================${NC}"
        echo ""
        echo "  API:    http://localhost:8000"
        echo "  Docs:   http://localhost:8000/docs"
        echo "  Health: http://localhost:8000/api/v1/health"
        echo ""
        echo "  Don't forget to:"
        echo "  - Setup Nginx reverse proxy"
        echo "  - Configure SSL (Let's Encrypt)"
        echo "  - Update DNS A record: api.staffbot.my → Server A IP"
        echo ""
        exit 0
    fi
    sleep 2
done

echo -e "${RED}Error: API failed to start within 60 seconds${NC}"
echo "Check logs: docker compose logs api"
exit 1
