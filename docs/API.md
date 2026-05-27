# API Reference — StaffBot.my

Base URL: https://staffbot.my/api/v1

## Authentication
Most endpoints require JWT Bearer token: Authorization: Bearer <token>
Get token via POST /api/v1/auth/login.

## Auth Endpoints
POST /auth/register - Create client account (201: {id, name, email, status})
POST /auth/login - Get JWT token ({access_token, token_type})
GET /auth/me - Current user profile (Auth required)
POST /auth/change-password - Update password (Auth required)

## Client Endpoints
GET /clients - List all clients (Admin only)
GET /clients/{id} - Get client details (Own profile or Admin)
PUT /clients/{id} - Update client profile (Own profile)
POST /clients/{id}/deploy - Force deploy container (Admin only)
POST /clients/setup - Complete onboarding wizard (Auth required)
GET /clients/{id}/api-keys - List API keys (Own keys)
POST /clients/{id}/platform/whatsapp - Initiate WhatsApp (Auth required)
POST /clients/{id}/platform/telegram - Register Telegram (Auth required)

## Package Endpoints
GET /packages/public - List public packages with pricing

## Webhook Endpoints
POST /webhooks/stripe - Stripe payment events
POST /webhooks/deploy - Server B container status callback

## Gateway Endpoints (Server B, internal)
GET /health - Gateway health check
POST /api/memory/search - Central Brain v2 hybrid search
POST /api/memory/save - Save memory to Central Brain
POST /api/deploy - Deploy client container
POST /api/container/{name}/start|stop|restart - Container lifecycle
DELETE /api/container/{name} - Remove container
PUT /api/container/{name}/resources - Update resource limits

## Gateway Request/Response Examples

### Memory Search
POST /api/memory/search
Headers: X-API-Key: gw-staffbot-secret-2026, Content-Type: application/json
Body: {"client_id": 1, "query": "customer inquiry", "limit": 5}
Response: {"success": true, "results": [...], "sources": {"vector":N,"keyword":N,"temporal":N,"graph":N}, "reranked": false}

### Memory Save
POST /api/memory/save
Headers: X-API-Key: gw-staffbot-secret-2026, Content-Type: application/json
Body: {"client_id": 1, "content": "memory text", "metadata": {"type":"note"}}
Response: {"success": true}

### Deploy Container
POST /api/deploy
Headers: X-API-Key: gw-staffbot-secret-2026, Content-Type: application/json
Body: {"client_id":1,"container_name":"staffbot-client-abc","subdomain":"abc123","env_vars":{...},"cpu_limit":1.0,"memory_limit_mb":512}
Response: {"port":9000,"container_id":"abc123..."}

## Error Responses
All endpoints return: {"detail": "message"}
200 Success, 201 Created, 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 409 Conflict, 500 Internal Error
