#!/usr/bin/env bash
# Integration tests for the managed Hermes platform and the security fixes.
#
# Needs: Python deps from api/requirements.txt (+ playwright for the browser
# test), and a THROWAWAY Postgres database that each suite drops/recreates:
#   export STAFFBOT_TEST_DATABASE_URL=postgresql://t:t@localhost:5432/t
#   export TEST_DB_ADMIN="sudo -u postgres psql"        # how to reset the DB
#   bash api/tests/integration/run_all.sh
# Docker is NOT needed: Docker, Hermes and the channel managers are faked.
set -uo pipefail
cd "$(dirname "$0")/../.."
DB_NAME=$(python3 -c "import os,urllib.parse as u;print(u.urlparse(os.environ.get('STAFFBOT_TEST_DATABASE_URL','postgresql://t:t@localhost:5432/t')).path.lstrip('/'))")
DB_OWNER=$(python3 -c "import os,urllib.parse as u;print(u.urlparse(os.environ.get('STAFFBOT_TEST_DATABASE_URL','postgresql://t:t@localhost:5432/t')).username)")
ADMIN=${TEST_DB_ADMIN:-"sudo -u postgres psql"}
fail=0
for t in test_phase0 test_llm_proxy test_orchestrator test_api_fixes test_gateway_fixes \
         test_agent_tools test_channels test_migration test_portal_e2e; do
  $ADMIN -q -c "DROP DATABASE IF EXISTS $DB_NAME;" -c "CREATE DATABASE $DB_NAME OWNER $DB_OWNER;" >/dev/null
  line=$(python tests/integration/$t.py 2>&1 | grep -E '^(FAIL|[0-9]+/[0-9]+ passed)')
  echo "$t: $(echo "$line" | tail -1)"
  echo "$line" | grep '^FAIL' && fail=1
done
exit $fail
