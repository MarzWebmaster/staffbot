# Skema Pangkalan Data — StaffBot.my

> Berdasarkan model SQLAlchemy (`api/app/models/`) dan SQL dalam repo, 19 Okt 2026.
> Skema live mungkin berbeza kerana perubahan dibuat secara manual dengan `psql`. **[SAHKAN-SERVER]** Jalankan `\d` pada setiap jadual.

## 1. Pangkalan data

| DB | Container | Digunakan oleh |
| :--- | :--- | :--- |
| `staffbot_db` | `staffbot-db` (pgvector/pg16, 127.0.0.1:5433) | API dan gateway (gateway turut menulis `chat_messages`, `token_usage_log`, `subscriptions`) |
| `staffbot_memory` | `staffbot-memory-db` (127.0.0.1:5434) | `server-b/docker-compose.yml`, iaitu laluan lama. Kemungkinan besar `client_memory` sebenar berada dalam `staffbot_db` **[SAHKAN-SERVER]** |

## 2. Konvensyen

- **PK**: semuanya `Integer` autoincrement (SERIAL). Tiada UUID.
- **Masa**: `DateTime` naif (UTC). Pengecualian: `client_email_configs.created_at` (timezone-aware) dan `subdomains` (waktu tempatan server).
- **Wang**: semuanya `Float`, bukan `Numeric`.
- **Tenant**: lajur `client_id` FK → `clients.id`.
- **Migrasi**: ❌ tiada Alembic. `Base.metadata.create_all()` dijalankan semasa startup (`database.py:34`). Fungsi ini **tidak mengubah jadual sedia ada**, jadi perubahan lajur dibuat dengan `psql` secara manual.

## 3. Jadual teras

### clients (tenant dan login)
`id`, `name`, `email` (unique), `password_hash` (bcrypt), `company`, `phone`, `package` (string, tiada FK ke `packages.name`), `status` (pending/active/suspended), `subdomain` (unique), `container_port`, `container_id`, `telegram_token_encrypted` 🔒, `whatsapp_number`, `whatsapp_auth_path`, `created_at`, `updated_at`.

### subscriptions (1:1 dengan clients)
`client_id` (unique, CASCADE), `stripe_subscription_id`, `stripe_session_id`, `package`, `status`, `managed_token_quota`, `managed_token_used`, `provider_token_usage` (JSON), `start_date`, `end_date`.

### packages
`name` (unique), `display_name`, `price_monthly`, `price_yearly`, `description`, `features` (JSON), `bot_limit`, `sub_ejen_limit`, `managed_tokens`, `cpu_limit`, `memory_limit_mb`, `storage_limit_gb`, `skill_category_ids`/`tool_category_ids` (INT[]), `allowed_skill_categories`/`allowed_tool_categories` (JSON), `enabled_skills`/`enabled_tools` (JSON), `sort_order`, `trial_days`, `is_public`, `is_active`, `badge`.
⚠️ Kod turut membaca `memory_retention_days`, `memory_item_limit` dan `knowledge_item_limit`, yang **tiada dalam model**.

### containers ("AI Staff" / bot)
`client_id`, `name`, `agent_name`, `container_name`, `image` (default `staffbot-core:latest`), `port`, `env_vars`, `status`, `skills`, `tools` (JSON).

### api_keys (BYOK)
`client_id`, `provider`, `key_encrypted` 🔒, `key_prefix`, `is_active`, `is_managed`.

### llm_providers / package_providers
- `llm_providers`: `name` (unique), `display_name`, `base_url`, `api_key_encrypted` 🔒, `models` (JSON), `default_model`, `is_active`, `sort_order`.
- `package_providers`: `package_id`, `provider_id`, `token_quota` (tidak dikuatkuasakan), `is_available`.

### chat_messages
`client_id`, `container_id`, `role` (user/assistant), `content`, `model`, `provider`, `tokens_used`, `created_at`.

### token_usage_log
`client_id`, `provider`, `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cost`, `endpoint`, `created_at`. Ditulis oleh gateway.

### audit_trail
`client_id`, `action`, `resource`, `detail` (JSONB), `ip_address`, `user_agent`, `status`, `created_at`.

### tasks
`client_id`, `container_id`, `title`, `description`, `priority`, `status`, `assigned_to`, `created_by_agent`.

## 4. Konfigurasi tool per klien

| Jadual | Lajur utama | 🔒 |
| :--- | :--- | :--- |
| `client_webhooks` | name, base_url, auth_type (none/bearer/api_key/basic), auth_header, auth_value, default_headers, rate_limit, max_timeout | auth_value |
| `client_search_configs` | provider (brave/…), api_key, base_url | api_key |
| `client_email_configs` | smtp_host, smtp_port, smtp_user, smtp_pass, use_tls, from_email, from_name | smtp_pass |

## 5. Jadual sokongan

| Jadual | Kegunaan |
| :--- | :--- |
| `settings` | Kunci/nilai global. `value` disulitkan bila `encrypted=true`. Contoh: kunci Stripe, `governance_policy` |
| `notification_channels`, `notifications_log` | Saluran notifikasi klien dan log penghantaran |
| `subdomains` | Senarai subdomain (available/assigned) |
| `token_topup_packages`, `token_topups` | Pakej top-up dan sejarah pembelian |
| `affiliates`, `affiliate_referrals`, `affiliate_commissions`, `affiliate_payouts`, `affiliate_clicks` | Program affiliate. ⚠️ `affiliate_payouts.account_details` (maklumat bank) **tidak disulitkan** |
| `policy_violations` | Log pelanggaran moderasi |

## 6. Jadual yang tiada DDL dalam repo (wujud di server?) [SAHKAN-SERVER]

| Jadual | Digunakan oleh |
| :--- | :--- |
| `client_memory` (versi penuh: title, memory_type, importance, source, file_*, chunk_index, total_chunks, parent_id, is_archived, `embedding vector(1536)`) | API `routers/memory.py`, gateway |
| `memory_audit_log` | `routers/memory.py`, `admin/users.py` |
| `skills_registry` (788 baris dari `merge_skills.sql`) | admin packages/policy |
| `tool_categories` | `admin/packages.py` |
| `soul_config` (category, key, value) | hermes-gateway, hermes-core. ⚠️ `init-memory.sql` mencipta `soul_configs` (nama dan struktur berbeza) |
| `audit_log` | hermes-gateway `security.py` |

## 7. Penyulitan

- **Algoritma**: Fernet (AES-128-CBC + HMAC-SHA256), `api/app/utils/encryption.py`.
- **Kunci**: `urlsafe_b64encode(sha256(STAFFBOT_SECRET_KEY))`. Tiada salt, tiada versi kunci, tiada rotasi.
- **Kunci yang sama digunakan untuk menandatangani JWT.** Menukar `STAFFBOT_SECRET_KEY` akan:
  - memadam log semua pengguna;
  - **menjadikan semua secret yang disulitkan tidak boleh dibaca**.
- Jika `STAFFBOT_SECRET_KEY` tidak ditetapkan, kunci diambil dari `/app/data/.secret_key` atau dijana secara automatik. Jika `/app/data` tidak kekal, semua secret hilang.
- Lajur disulitkan (🔒): `clients.telegram_token_encrypted`, `api_keys.key_encrypted`, `llm_providers.api_key_encrypted`, `settings.value` (bila `encrypted`), `client_webhooks.auth_value`, `client_search_configs.api_key`, `client_email_configs.smtp_pass`.

## 8. Konsep yang TIADA

Pengguna dalam satu syarikat (staf), jadual peranan, cawangan, jabatan, kelulusan, refresh token, device token, `sop_documents` / `sop_chunks` khusus, dan usage log per pengguna.
