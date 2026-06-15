# StaffBot Gateway Tools Enhancement Plan

> Temporary reference doc — last updated: 15 Jun 2026

---

## Fasa 0: Sedia Ada ✅

| # | Tool | Status | Fungsi |
|---|------|--------|--------|
| 1 | `search_memory` | ✅ Live | Search pgvector memory |
| 2 | `get_current_time` | ✅ Live | Current timestamp |
| 3 | `save_to_memory` | ✅ Live | Save facts/preferences |
| — | ReAct loop | ✅ Live | Tool-calling loop in gateway |
| — | Audit trail | ✅ Live | 8 event paths, asyncpg |
| — | Token quota | ✅ Live | Deduct per chat message |
| — | Encrypted keys | ✅ Live | STAFFBOT_SECRET_KEY |

---

## Fasa 1: DB + Model `client_webhooks` 🆕

**Masa:** 45 min

| Task | Detail |
|------|--------|
| Table | `client_webhooks` — id, client_id, name, base_url, auth_type, auth_header, auth_value (encrypted), default_headers (JSONB), is_active, rate_limit, created_at |
| Model | SQLAlchemy model dlm `api/app/models/` |
| CRUD API | Endpoints: `POST/GET/PUT/DELETE /api/v1/webhooks/config` |
| Encryption | Guna `STAFFBOT_SECRET_KEY` — sama mcm provider keys |

### Table Schema
```sql
client_webhooks:
  id              SERIAL PRIMARY KEY
  client_id       INTEGER FK → clients(id) ON DELETE CASCADE
  name            VARCHAR(100) NOT NULL          -- "My WordPress"
  base_url        VARCHAR(500) NOT NULL           -- https://mysite.com/wp-json
  auth_type       VARCHAR(20) DEFAULT 'none'      -- none|bearer|api_key|basic
  auth_header     VARCHAR(50)                      -- X-API-Key, Authorization
  auth_value      TEXT                             -- ENCRYPTED token/key
  default_headers JSONB DEFAULT '{}'
  is_active       BOOLEAN DEFAULT true
  rate_limit      INTEGER DEFAULT 10              -- max calls/min
  created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

## Fasa 2: `call_webhook` Gateway Tool 🆕

**Masa:** 60 min

| Task | Detail |
|------|--------|
| Tool definition | OpenAI function-calling spec |
| HTTP executor | `httpx.AsyncClient` — GET/POST/PUT/DELETE |
| Auth injection | Bearer/API-Key/Basic dari DB (decrypt at runtime) |
| Sandbox | Block internal IP, URL must match base_url, 30s timeout |
| Rate limit | 10 calls/min per client (token bucket in-memory) |
| Audit | Log setiap call — method, url, status_code, duration |

### Tool Spec
```yaml
call_webhook:
  parameters:
    endpoint_name:  string  # must match client_webhooks.name
    path:           string  # e.g. /wp/v2/posts
    method:         enum[GET, POST, PUT, DELETE]
    body:           object  # optional JSON
    query_params:   object  # optional key=value
```

### Security Rules
- ✅ URL must start with client's `base_url`
- ✅ Block internal IP: `127.x`, `10.x`, `172.16-31.x`, `192.168.x`
- ✅ Auth value NEVER sent to LLM — injected server-side only
- ✅ Max response size: 100KB
- ✅ Audit logged (async, non-blocking)

---

## Fasa 3: `web_search` Tool 🆕

**Masa:** 30 min

| Task | Detail |
|------|--------|
| Provider | Brave Search API (free tier: 2000 queries/month) |
| Config | Admin global key simpan encrypted dlm `settings` table |
| Rate limit | 20 searches/min per client |
| Audit | Log query + result count |

### Tool Spec
```yaml
web_search:
  parameters:
    query:  string  # search query
    count:  integer # results to return (1-10, default 5)
```

---

## Fasa 4: `send_email` Tool 🆕

**Masa:** 30 min

| Task | Detail |
|------|--------|
| Option A | Customer set SMTP sendiri (host, port, user, pass encrypted) |
| Option B | Guna `call_webhook` → SendGrid/Mailgun/etc |
| Rate limit | 50 emails/hari per client |
| Audit | Log recipient + subject |

### Tool Spec
```yaml
send_email:
  parameters:
    to:       string  # recipient
    subject:  string
    body:     string  # plain or HTML
    cc:       string  # optional
```

---

## Fasa 5: `create_document` Tool 🆕

**Masa:** 45 min

| Task | Detail |
|------|--------|
| Word | `python-docx` library |
| PowerPoint | `python-pptx` library |
| Excel | `openpyxl` library |
| Execution | Server-side only (no external API) |
| Temp file | Auto-cleanup after 5 min |
| Limit | Max 5MB output |
| Audit | Log doc_type + file_size |

### Tool Spec
```yaml
create_document:
  parameters:
    doc_type:   enum[word, powerpoint, excel]
    title:      string
    content:    array  # structured content blocks
    filename:   string  # optional
```

---

## Fasa 6: Self-Service Setup via Chat 🆕

**Masa:** 45 min

| Task | Detail |
|------|--------|
| Intent detection | Detect "connect", "link", "setup" + service name |
| Info extraction | Parse URL, auth type, token dari natural language |
| Confirmation | AI summarize config → customer confirm sebelum save |
| CRUD via chat | Create/Update/Delete webhooks through conversation |

### Flow
```
User: "connect my WordPress at https://mysite.com/wp-json 
       with API key wp_sk_xxxxx"

AI:    "I'll set up WordPress connection:
        • Name: My WordPress
        • URL: https://mysite.com/wp-json
        • Auth: API Key
        Confirm? (yes/no)"

User:  "yes"

AI:    "✅ WordPress connected! Try: 'create a draft post...'"
```

---

## Fasa 7: Policy UI (Admin) 🆕

**Masa:** 20 min

| Task | Detail |
|------|--------|
| Panel | Dlm admin dashboard — tab "Tools" atau dlm client edit page |
| Toggle | Enable/disable: call_webhook, web_search, send_email, create_document |
| Override | Rate limit custom per client |

---

## Fasa 8: End-to-End Testing 🆕

**Masa:** 30 min

| Test Case | Service | Verify |
|-----------|---------|--------|
| WordPress REST | GET /wp/v2/posts | Returns posts array |
| HubSpot API | POST /crm/v3/objects/contacts | Contact created |
| CRM generic | POST /api/leads | Lead saved |
| SendGrid | POST /v3/mail/send | Email delivered |
| Generate Word | create_document → .docx | File dihasilkan |
| Web search | "cuaca Malaysia hari ini" | Returns results |
| Security | Block internal IP | 403 Forbidden |
| Security | Cross-client access | 403 Forbidden |
| Security | Audit log verify | Row exists in audit_trail |

---

## Timeline Ringkasan

```
Fasa 0  ████████████████ ✅ Siap
Fasa 1  ████████         🆕 45m   — DB + Model
Fasa 2  ████████████     🆕 60m   — call_webhook tool
Fasa 3  ██████           🆕 30m   — web_search tool
Fasa 4  ██████           🆕 30m   — send_email tool
Fasa 5  █████████        🆕 45m   — create_document tool
Fasa 6  █████████        🆕 45m   — self-service chat
Fasa 7  ████             🆕 20m   — policy UI
Fasa 8  ██████           🆕 30m   — testing
────────────────────────────────────────
Total baru:  ~5 jam
```

---

## Key Design Decisions

1. **`call_webhook` is the core** — covers 80% of use cases (WordPress, HubSpot, CRM, leads, email APIs)
2. **Auth encryption** — reuse existing `STAFFBOT_SECRET_KEY`, same as provider keys
3. **Sandbox at gateway level** — IP filtering, URL whitelist, rate limits all in one place
4. **Self-service via chat** — no need web UI, natural language setup
5. **All audit logged** — same `audit_trail` table, async non-blocking
6. **Per-client isolation** — webhooks scoped to client_id, cannot cross
