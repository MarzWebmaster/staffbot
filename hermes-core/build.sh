#!/usr/bin/env bash
# StaffBot.my — Build Hermes Core Docker Image
# =============================================
# Builds the staffbot-hermes-core image with all skills/tools pre-loaded.
# Run from the staffbot/hermes-core/ directory.
#
# Usage:
#   bash build.sh                    # Build tag staffbot-hermes-core:latest
#   bash build.sh v1.0.0            # Build with specific version tag
#   bash build.sh v1.0.0 --no-cache # Force fresh build
#
# After building, push to registry:
#   docker tag staffbot-hermes-core:v1.0.0 your-registry/staffbot-hermes-core:v1.0.0
#   docker push your-registry/staffbot-hermes-core:v1.0.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}  StaffBot.my — Hermes Core Image Builder   ${NC}"
echo -e "${YELLOW}============================================${NC}"

# ── Version tag ─────────────────────────────────────────────────────
VERSION="${1:-latest}"
shift 2>/dev/null || true
EXTRA_ARGS="$@"

IMAGE_NAME="staffbot-hermes-core:${VERSION}"
echo -e "${GREEN}Building: ${IMAGE_NAME}${NC}"

# ── Check Hermes repo exists ────────────────────────────────────────
HERMES_REPO="/home/marz/.hermes/hermes-agent"
if [ ! -d "$HERMES_REPO" ]; then
    echo -e "${RED}Error: Hermes Agent repo not found at ${HERMES_REPO}${NC}"
    echo "Clone it first: git clone https://github.com/nousresearch/hermes-agent.git $HERMES_REPO"
    exit 1
fi

# ── Build context: we need the Hermes Agent repo as base ─────────────
# The Dockerfile references files from both the Hermes repo AND our
# StaffBot extensions. We build from our directory which has:
#   Dockerfile           ← our StaffBot Dockerfile
#   scripts/             ← StaffBot custom scripts
#   templates/           ← StaffBot templates
#   docker/              ← StaffBot entrypoint
#
# The Dockerfile pulls FROM ghcr.io/nousresearch/hermes-agent:latest
# so the Hermes repo doesn't need to be in the build context.

echo -e "${GREEN}[1/3] Building image...${NC}"
docker build \
    --tag "${IMAGE_NAME}" \
    --label "staffbot.version=${VERSION}" \
    --label "staffbot.built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    ${EXTRA_ARGS} \
    .

echo -e "${GREEN}[2/3] Image built successfully!${NC}"

# ── Also tag as latest if versioned ─────────────────────────────────
if [ "$VERSION" != "latest" ]; then
    docker tag "${IMAGE_NAME}" "staffbot-hermes-core:latest"
    echo -e "${GREEN}  → Also tagged as staffbot-hermes-core:latest${NC}"
fi

# ── Show image info ─────────────────────────────────────────────────
echo -e "${GREEN}[3/3] Image details:${NC}"
docker images staffbot-hermes-core --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

echo ""
echo -e "${YELLOW}============================================${NC}"
echo -e "${GREEN}  Build Complete!${NC}"
echo -e "${YELLOW}============================================${NC}"
echo ""
echo "  Image: ${IMAGE_NAME}"
echo "  Size:  $(docker images staffbot-hermes-core --format '{{.Size}}' | head -1)"
echo ""
echo "  To push to registry:"
echo "    docker tag ${IMAGE_NAME} your-registry/staffbot-hermes-core:${VERSION}"
echo "    docker push your-registry/staffbot-hermes-core:${VERSION}"
echo ""
echo "  To deploy to Server B:"
echo "    # Save image as tar"
echo "    docker save ${IMAGE_NAME} -o /tmp/staffbot-hermes-core-${VERSION}.tar"
echo "    # Transfer to Server B"
echo "    scp /tmp/staffbot-hermes-core-${VERSION}.tar root@server-b:/tmp/"
echo "    # Load on Server B"
echo "    ssh root@server-b 'docker load -i /tmp/staffbot-hermes-core-${VERSION}.tar'"
echo ""
