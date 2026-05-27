# Product Requirements Document — StaffBot.my

## 1. Product Overview

StaffBot.my is a Digital Employee as a Service (DEaaS) platform. Clients hire dedicated AI employees that work 24/7 across WhatsApp, Telegram, and web dashboard.

### Problem Statement
Malaysian SMEs struggle with high cost of hiring full-time staff (RM2k-3k per employee), staff turnover and retraining costs, limited hours of operation (8-10 hrs/day), and inability to automate customer service, sales, and operations.

### Solution
Dedicated AI agents per client that cost RM49-499/month per agent, work 24/7, never take leave, learn company SOPs in 24 hours, execute tasks autonomously, and remember context across sessions.

## 2. Target Market
- Primary: Malaysian SMEs (retail, F&B, property, healthcare, professional services)
- Secondary: E-commerce businesses needing 24/7 WhatsApp support
- Tertiary: Regional expansion (SE Asia)

## 3. Core Features

### Phase 1 — MVP (Current)
- Client registration and authentication
- Package-based subscription (Basic RM49 / Business RM99 / Enterprise RM499)
- Dedicated AI agent container per client
- WhatsApp auto-reply via Baileys multi-session
- Telegram bot integration
- Central Brain v2 memory system (4-strategy hybrid search, zero LLM cost)
- Admin panel with client management
- Admin force deploy endpoint
- OCR and document scanning (tesseract, pymupdf, pytesseract)
- SEO-optimized landing page with GEO support

### Phase 2 — Coming
- Multi-agent teams per client
- Advanced analytics dashboard
- Custom skill marketplace
- API access for developers
- Mobile app

## 4. User Stories

### Client
- Register and get AI agent deployed immediately
- Connect WhatsApp so customers can message my AI
- Upload company documents so AI learns my business
- AI auto-replies to customer inquiries 24/7

### Admin
- View all clients and their status
- Force deploy containers for clients
- Manage packages and pricing
- Monitor system health

## 5. Technical Requirements

### Performance
- Container startup: under 30 seconds
- AI response time: under 5 seconds
- Memory search: under 500ms
- 99.9% uptime SLA

### Security
- Isolated Docker containers per client
- Encrypted storage for API keys (AES-256)
- No cross-client data access
- Rate limiting on API endpoints
- Cloudflare DDoS protection

### Scalability
- Horizontal scaling of client containers
- Database connection pooling
- Async processing for webhooks
