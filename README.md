# StaffBot.my — AI Employee Platform

> Hire AI Staff That Actually Works — Dedicated AI employees for customer service, sales, marketing and business management.

**Version:** 2.0.0
**Company:** Marz Technology and Trading (SSM: 202303107389)
**Website:** https://staffbot.my

---

## Overview

StaffBot.my is Malaysia's AI Employee Platform. Each client gets a dedicated, isolated AI agent container trained on their business data, connected to WhatsApp/Telegram, capable of executing tasks autonomously.

### Key Features
- Dedicated AI Agents with per-client isolated containers
- WhatsApp AI Chatbot with auto-reply and lead generation
- Business Automation and workflow automation
- Full Integration with Google Drive, Email, Stripe, CRM, APIs
- Smart Memory with persistent context (pgvector + Central Brain v2)
- Secure and Isolated Docker containers
- OCR and Document Scanning (PDF, images, scanned docs)

### Skill Categories
1. Communication and Auto-Reply
2. Sales and Marketing
3. Content and Documentation (OCR, diagrams, image gen)
4. Operations and Automation (multi-step orchestration)
5. Customer Support
6. Analytics and Reports (self-writing BI)
7. Schedule and Calendar
8. Finance and Invoice
9. Industry Specific
10. Learning and Adaptation

---

## Architecture

Server A (Tencent Cloud):
- staffbot-api (FastAPI, port 8000)
- staffbot-db (PostgreSQL 16, port 5433)
- staffbot-gateway (Central Brain v2, port 8080)
- staffbot-baileys (WhatsApp multi-session, port 8653)
- staffbot-telegram (Telegram multi-bot, port 8654)
- Client Containers (isolated per client, ports 9xxx)

See docs/ARCHITECTURE.md for full details.

---

## Quick Start

Prerequisites: Docker, Docker Compose, PostgreSQL 16, Cloudflare account, OpenRouter API key.

Development:
```
git clone https://github.com/MarzWebmaster/staffbot.git
cd staffbot/api
cp .env.example .env
docker compose up -d
```

See docs/DEPLOYMENT.md for production guide.
