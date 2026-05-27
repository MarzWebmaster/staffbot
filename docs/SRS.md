# Software Requirements Specification — StaffBot.my

## 1. Introduction

### 1.1 Purpose
This document defines the software requirements for StaffBot.my, an AI Employee Platform for Malaysian businesses.

### 1.2 Scope
The system comprises API backend (FastAPI), Database (PostgreSQL 16), AI Gateway (Central Brain v2), WhatsApp handler (Baileys), Telegram handler, Client agent containers, Landing page, and Admin panel.

### 1.3 Definitions
- AI Agent: Dedicated container running per client with Hermes Agent runtime
- Central Brain: Hybrid memory search system using pgvector with 4 strategies
- Baileys: WhatsApp Web library for message handling (multi-session)
- Client: Paying customer with a deployed container

## 2. Functional Requirements

### FR1: Client Management
- FR1.1 Register new client with name, email, phone, company
- FR1.2 Authenticate via JWT tokens
- FR1.3 Update client profile
- FR1.4 Admin list/search clients with filters
- FR1.5 Admin force deploy client container

### FR2: Package Management
- FR2.1 Create/edit packages with pricing
- FR2.2 Assign skill and tool categories per package
- FR2.3 Set token quotas per package
- FR2.4 Package tiers: Basic (RM49), Business (RM99), Enterprise (RM499)

### FR3: Container Deployment
- FR3.1 Generate unique subdomain from company name
- FR3.2 Create Cloudflare DNS record
- FR3.3 Deploy Docker container on Server B
- FR3.4 Set resource limits (CPU, RAM, storage) per package
- FR3.5 Update client status to active
- FR3.6 Send deployment notifications (WhatsApp, email, in-app)

### FR4: WhatsApp Integration
- FR4.1 Initiate Baileys session per client
- FR4.2 Generate QR code for WhatsApp linking
- FR4.3 Handle incoming text and media messages
- FR4.4 Route messages to correct client container
- FR4.5 Multi-session support for multiple clients

### FR5: Telegram Integration
- FR5.1 Register webhook for client bot token
- FR5.2 Handle incoming Telegram messages
- FR5.3 Route messages to correct client container

### FR6: Memory System (Central Brain v2)
- FR6.1 4-strategy hybrid search (vector ILIKE, keyword tsvector, temporal, graph)
- FR6.2 Save memory with metadata
- FR6.3 RRF merge across all strategies
- FR6.4 Optional cross-encoder rerank
- FR6.5 Zero external LLM cost for memory operations

### FR7: OCR and Document Processing
- FR7.1 Extract text from PDF files via pymupdf
- FR7.2 OCR from images via tesseract
- FR7.3 Support Bahasa Melayu OCR (tesseract-ocr-msa)
- FR7.4 Extract text from Word documents via python-docx
- FR7.5 Extract data from Excel files via openpyxl

### FR8: Notifications
- FR8.1 Send WhatsApp notification on deployment complete
- FR8.2 Send email notification on deployment complete
- FR8.3 Notify admin on new registration
- FR8.4 Notify admin on payment received

## 3. Non-Functional Requirements

### NFR1: Performance
- API response time under 200ms (p95)
- Container deployment under 30 seconds
- Memory search under 500ms
- Concurrent support for 200+ clients

### NFR2: Security
- Passwords hashed with bcrypt
- API keys encrypted at rest (AES-256)
- JWT tokens with 24h expiry
- CORS restricted to staffbot.my
- All internal ports bound to localhost via Docker

### NFR3: Reliability
- Database health checks every 5 seconds
- Container auto-restart on failure (restart: unless-stopped)
- Connection pooling for PostgreSQL

## 4. Database Tables

### Core Tables
- clients (id, name, email, password_hash, company, phone, package, status, subdomain, container_port, container_id, telegram_token_encrypted, whatsapp_number, whatsapp_auth_path, created_at, updated_at)
- subscriptions (id, client_id, stripe_session_id, package, status, managed_token_quota, start_date, end_date)
- packages (id, name, display_name, description, price_monthly, bot_limit, sub_ejen_limit, managed_tokens, skill_category_ids, tool_category_ids, badge, trial_days, is_active)
- skill_categories (id, name, display_name, icon, description, sort_order, is_active)
- tool_categories (id, name, description)

### Support Tables
- api_keys (id, client_id, provider, key_encrypted, key_prefix, is_active, is_managed)
- containers (id, client_id, container_name, docker_id, status, port, subdomain)
- token_usage_log (id, client_id, tokens, endpoint, created_at)
- notification_channels (id, client_id, channel, config, is_active)
- notifications_log (id, client_id, channel, subject, body, status, created_at)
- client_memory (id, client_id, content, metadata, created_at, content_tsv)

## 5. API Endpoints Summary

### Public
POST /api/v1/auth/register, POST /api/v1/auth/login, GET /api/v1/packages/public

### Admin
GET /api/v1/clients, POST /api/v1/clients/{id}/deploy, PUT /api/v1/clients/{id}

### Client
GET/PUT /api/v1/clients/{id}, POST /api/v1/clients/setup
POST /api/v1/clients/{id}/platform/whatsapp
POST /api/v1/clients/{id}/platform/telegram

### Internal (Gateway)
POST /api/memory/search, POST /api/memory/save
POST /api/deploy, Container lifecycle endpoints
