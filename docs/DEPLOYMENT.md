# Deployment Guide — StaffBot.my

## Production Server
IP: 43.156.204.227 (Tencent Cloud)
SSH Key: /home/marz/.hermes/theceo_key.pem
SSH Port: 333
Domain: staffbot.my, api.staffbot.my

## Initial Setup
Clone repo: git clone https://github.com/MarzWebmaster/staffbot.git /root/staffbot
Configure .env with DB password, OpenRouter key, Stripe key, Cloudflare token
Run: docker compose up -d from /root/staffbot/api/

## Deploying Code Changes

### Static Files (Landing Page, CSS)
Volume-mounted so instant. Copy to /root/staffbot/api/app/static/ then test with ?nocache=X.

### API Code Changes
cd /root/staffbot/api && docker compose build api && docker compose up -d api

### Gateway Changes (Central Brain)
cd /root/staffbot/server-b && docker build -t staffbot-gateway:latest ./gateway/
docker compose -f /root/staffbot/api/docker-compose.yml up -d gateway

### Core Image Changes
cd /root/staffbot/server-b && docker build -t staffbot-core:latest ./core-image/
Client containers use new image on next deploy.

## Database Migrations
Add column: docker exec staffbot-db psql -U staffbot -d staffbot_db -c "ALTER TABLE clients ADD COLUMN IF NOT EXISTS col TYPE;"
Create memory table must be done manually.

## Monitoring
- Container status: docker ps --format
- Logs: docker logs staffbot-api --tail 50
- Gateway health: curl http://127.0.0.1:8080/health
- Memory search test: curl POST /api/memory/search with X-API-Key

## Git Workflow
cd /root/staffbot && git add . && git commit -m "msg" && git push origin main

## Troubleshooting
- Container wont start: docker logs <name> --tail 50
- Port conflict: docker ps | grep <port>
- DB error: docker exec staffbot-db pg_isready -U staffbot -d staffbot_db
- Cloudflare cache: always use ?nocache=X when testing
