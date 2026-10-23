#!/usr/bin/env bash
# One-time (idempotent) host setup for managed Hermes customer containers.
# Run as root on the customer node. See docs/RUNBOOK_MANAGED_HERMES.md.
#
#   sudo bash scripts/managed-hermes/setup-host.sh            # apply
#   sudo bash scripts/managed-hermes/setup-host.sh --check    # show rules only
#
# What it does:
#  1. Creates the customer network (172.30.0.0/16, bridge sb-customers, no
#     container-to-container traffic).
#  2. Creates host dirs for managed config and backups.
#  3. Firewall for traffic FROM customer containers:
#     - may reach the LLM proxy at 172.30.0.1:8090 and the public internet
#     - may NOT reach the host itself, private/Tailscale/link-local ranges,
#       other customers' published ports, or SMTP port 25
#  4. Optionally checks for gVisor (runsc).
set -euo pipefail

NET=staffbot-customers
BRIDGE=sb-customers
SUBNET=172.30.0.0/16
GW=172.30.0.1
PROXY_PORT=8090
MANAGED_DIR=/srv/staffbot/managed
BACKUP_DIR=/srv/staffbot/backups
BLOCKED="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 127.0.0.0/8 0.0.0.0/8 224.0.0.0/4"

if [[ "${1:-}" == "--check" ]]; then
  iptables -S DOCKER-USER | grep -E "$BRIDGE|STAFFBOT" || true
  iptables -S INPUT | grep -E "$BRIDGE" || true
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }

# 1. network
if ! docker network inspect "$NET" >/dev/null 2>&1; then
  docker network create --driver bridge --subnet "$SUBNET" --gateway "$GW" \
    -o com.docker.network.bridge.enable_icc=false \
    -o com.docker.network.bridge.name="$BRIDGE" \
    --label staffbot.type=customer-network "$NET"
fi

# 2. dirs (root-owned; managed files are world-readable, backups are not)
install -d -m 0755 -o root -g root "$MANAGED_DIR"
install -d -m 0700 -o root -g root "$BACKUP_DIR"

# 3. firewall. DOCKER-USER sees forwarded traffic after DNAT, so the proxy is
#    matched by its ORIGINAL destination (conntrack), and everything else that
#    lands on a private address is dropped.
add() { local chain=$1; shift; iptables -C "$chain" "$@" 2>/dev/null || iptables -I "$chain" "$@"; }

# Rules are inserted at the top, so add them in reverse order of evaluation.
add DOCKER-USER -i "$BRIDGE" -p tcp --dport 25 -j DROP -m comment --comment STAFFBOT-no-smtp25
for net in $BLOCKED; do
  add DOCKER-USER -i "$BRIDGE" -d "$net" -j DROP -m comment --comment STAFFBOT-block-private
done
add DOCKER-USER -i "$BRIDGE" -p tcp -m conntrack --ctorigdst "$GW" --ctorigdstport "$PROXY_PORT" -j ACCEPT -m comment --comment STAFFBOT-allow-proxy
add DOCKER-USER -i "$BRIDGE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT -m comment --comment STAFFBOT-established

# Customer containers may not talk to services on the host itself.
add INPUT -i "$BRIDGE" -j DROP
add INPUT -i "$BRIDGE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

echo "Firewall rules applied. Persist them (e.g. iptables-save > /etc/iptables/rules.v4)."

# 4. gVisor
if command -v runsc >/dev/null 2>&1 && docker info --format '{{json .Runtimes}}' | grep -q runsc; then
  echo "gVisor runtime available: set STAFFBOT_HERMES_RUNTIME=runsc"
else
  echo "gVisor (runsc) not installed. See https://gvisor.dev/docs/user_guide/install/ ; until then STAFFBOT_HERMES_RUNTIME must stay empty."
fi
