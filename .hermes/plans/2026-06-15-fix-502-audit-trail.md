# Fix 502 + Audit Trail Implementation Plan

> **Goal:** Fix 502 web chat error, remove dead Mimo/Jemaah provider, add system-wide audit trail

**Architecture:** Fix error swallowing in chat router → gateway, remove Mimo fallback, add `audit_logs` DB table + middleware

---

## Part A: Fix 502 — Surface Real Error

### Task A1: Fix chat.py — surface gateway error detail
**File:** `api/api/app/routers/chat.py` ~line 408
**Change:** When gateway returns non-200, read `resp.text` and include in error message
```python
if resp.status_code != 200:
    try:
        gw_detail = resp.json().get("detail", resp.text[:200])
    except:
        gw_detail = resp.text[:200]
    logger.error(f"Gateway {resp.status_code} for client #{client_id}: {gw_detail}")
    ...
    return {"success": False, "error": "gateway_error", "message": f"Gateway error: {gw_detail}"}
```

### Task A2: Fix chat.py — remove Mimo fallback (line 346-348)
**File:** `api/api/app/routers/chat.py` lines 346-348
**Change:** Delete the Mimo fallback block entirely
```python
# DELETE these 3 lines:
# Fallback: use default env LLM if no key found
# if not provider_api_key and MIMO_KEY:
#     provider_api_key = MIMO_KEY
```

### Task A3: Fix model fallback — use deepseek-v4-flash not mimo
**File:** `api/api/app/routers/chat.py` line 364
**Change:** Final fallback from `"mimo/mimo-v2.5"` to `"deepseek-v4-flash"`

### Task A4: Fix gateway.py — don't hardcode stream=False comment
**File:** `server-b/gateway/main.py` line 894
**Change:** Comment says "Jemaah/Mimo upstream requires non-streaming" — update to reflect DeepSeek

---

## Part B: Audit Trail System

### Task B1: Create audit_logs DB table
**File:** New migration / DB schema
**Schema:**
```sql
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id),
    action VARCHAR(50) NOT NULL,         -- 'chat_send', 'login', 'settings_change', etc.
    resource_type VARCHAR(50),           -- 'provider', 'package', 'message', etc.
    resource_id INTEGER,
    details JSONB DEFAULT '{}',          -- full context
    ip_address VARCHAR(45),
    user_agent TEXT,
    status VARCHAR(20) DEFAULT 'success', -- 'success', 'failed', 'blocked'
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_audit_client ON audit_logs(client_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);
```

### Task B2: Create AuditService
**File:** New `api/api/app/services/audit_service.py`
**API:**
```python
async def audit_log(
    db, client_id, action, resource_type=None, resource_id=None,
    details=None, ip_address=None, user_agent=None,
    status='success', error_message=None, duration_ms=None
)
```

### Task B3: Integrate audit into chat/send
**File:** `api/api/app/routers/chat.py`
**Points:**
- Log `chat_send` with model, provider, token usage
- Log on success AND on error (gateway error, timeout, moderation block)

### Task B4: Integrate audit into auth/login
**File:** `api/api/app/routers/auth.py`
**Points:** Log every login attempt with IP, status

### Task B5: Integrate audit into settings changes
**File:** `api/api/app/routers/admin/settings.py`
**Points:** Log provider changes, package changes, key updates

### Task B6: Add IP/user-agent extraction helper
**File:** `api/api/app/utils/request_utils.py`
**API:** `get_client_info(request: Request) -> dict`

---

## Part C: Deploy & Verify

### Task C1: Push to server via scp
### Task C2: Rebuild API + Gateway Docker images
### Task C3: Verify chat works + audit logs populate
