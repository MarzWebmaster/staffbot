#!/bin/bash
# Test LLM Provider Bridge end-to-end
set -e

echo "=== 1. Login ==="
LOGIN=*** -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"marz@staffbot.my","password":"Test1234"}')
TOKEN=*** "$LOGIN" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
if [ -z "$TOKEN" ]; then echo "Login FAILED: $LOGIN"; exit 1; fi
echo "Token OK: ${TOKEN:0:20}..."

echo ""
echo "=== 2. Current Config ==="
docker exec staffbot-gateway head -6 /app/data/config.yaml

echo ""
echo "=== 3. Update Provider (triggers regenerate) ==="
RESULT=*** -s -X PUT http://127.0.0.1:8000/api/v1/admin/llm/providers/5 \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer *** \
  -d '{"sort_order": 1}')
echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"

echo ""
echo "=== 4. Config After Update ==="
docker exec staffbot-gateway head -10 /app/data/config.yaml
echo ""
echo "=== 5. Hermes :8642 Health ==="
curl -s -o /dev/null -w 'HTTP %{http_code}' http://127.0.0.1:8642/
echo ""
