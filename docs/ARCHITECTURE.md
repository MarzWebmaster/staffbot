# System Architecture — StaffBot.my

## High-Level Architecture

Single-server topology (verified Oct 2026):

Production server (OVH, "OVH 2", hostname mail.pandaibot.my):
- Runs ALL StaffBot services as one Docker stack (the former "Server A" and
  "Server B" services: staffbot-api, staffbot-db, staffbot-gateway,
  staffbot-memory-db, staffbot-baileys, staffbot-telegram, staffbot-embeddings)
- Client containers (isolated per client, ports 9xxx)
- Public-facing HTTPS via Cloudflare CDN; nginx vhosts in /etc/nginx/conf.d/
- Shared host: also runs pandaibot (PHP, scheduler, Redis, MySQL) and a mail
  server (Postfix/Dovecot)
- Admin access: SSH over Tailscale only (node: ovh-staffbot)

Server IPs, SSH ports and credentials are deliberately NOT kept in this repo.
Store them in the team password manager.

Note: earlier versions of this doc listed a Tencent Cloud "Server A" and a
Contabo "Server B". Those entries are outdated.

## Service Topology

### Internal Docker Network (10.100.0.0/24)
staffbot-api :8000 communicates with staffbot-gateway :8080
staffbot-gateway :8080 communicates with staffbot-db :5432
staffbot-baileys :8653 communicates with staffbot-gateway :8080
staffbot-telegram :8654 communicates with staffbot-gateway :8080
Client containers :9xxx communicate with staffbot-gateway :8080

### External Access
staffbot.my points to Cloudflare which proxies to staffbot-api :8000
api.staffbot.my points to Cloudflare which proxies to staffbot-api :8000
client-xxx.staffbot.my points to Cloudflare which proxies to client container :9xxx

## Database Architecture

### staffbot_db (PostgreSQL 16 on port 5433)
Main application database for clients, packages, subscriptions, settings.

### client_memory (in staffbot_db)
Central Brain v2 memory storage with tsvector index and created_at timestamps.

## Central Brain v2

4-strategy hybrid search system with RRF merge:

### Strategy 1: Vector (ILIKE)
Simple PostgreSQL ILIKE pattern matching on memory content. Fast fallback strategy.

### Strategy 2: Keyword (tsvector)
PostgreSQL full-text search with stemming, normalization, stop word removal, and ts_rank scoring.

### Strategy 3: Temporal (created_at DESC)
Recent-first ordering. Boosts recently saved memories in final ranking.

### Strategy 4: Graph/Entity (keyword overlap)
Extracts keywords from query, matches against memory content using word overlap scoring.

### RRF Merge
Reciprocal Rank Fusion combines all 4 strategies:
RRF score = sum of 1/(k + rank_per_strategy) for each item
Final results sorted by total RRF score descending.

## Client Container Architecture

Based on staffbot-core:latest Docker image:
- Python 3.12 slim base
- FastAPI + uvicorn web server
- Hermes Agent runtime
- OCR libraries: tesseract-ocr, pymupdf, pytesseract
- Document processing: python-docx, openpyxl
- Image processing: Pillow
- Bahasa Melayu OCR support: tesseract-ocr-msa

Resource limits per package:
- Basic: 0.5 CPU, 512MB RAM, 10GB storage
- Business: 1 CPU, 1GB RAM, 20GB storage
- Enterprise: 2 CPU, 2GB RAM, 50GB storage

## Data Flow Diagrams

### Incoming WhatsApp Message
User sends WhatsApp -> Baileys Manager receives event -> Forwards to Gateway -> Gateway routes to client container -> AI processes and responds -> Response back via Baileys.

### New Client Registration
Client registers via landing page -> Auth creates client (pending) -> Admin force-deploys -> DeploymentService generates subdomain -> Cloudflare DNS created -> Container deployed on the production server -> Client status active -> Notifications sent.

### Memory Save and Search
Agent calls /api/memory/save -> Gateway stores in client_memory table with tsvector.
Agent calls /api/memory/search -> Gateway runs 4 strategies in parallel -> RRF merges results -> Cross-encoder reranks (optional) -> Returns results.
