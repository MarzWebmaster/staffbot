# SRS — StaffBot.my (keadaan sebenar)

> Versi 2.0 (19 Okt 2026). Setiap keperluan diberi status berdasarkan kod sebenar, dengan rujukan `fail:baris`.
> ✅ berfungsi · ⚠️ separa / ada bug · ❌ tiada · **[SAHKAN-SERVER]** perlu disemak di server.

## 1. Pengenalan

### 1.1 Skop sistem

| Komponen | Kod | Container |
| :--- | :--- | :--- |
| API backend (FastAPI, 2 worker) | `api/app/` | `staffbot-api` :8000 |
| Pangkalan data utama (Postgres 16 + pgvector) | — | `staffbot-db` :5433 |
| Gateway AI (FastAPI tersuai, ReAct + tool) | `server-b/gateway/main.py` | `staffbot-gateway` :8080 |
| Hermes gateway (NousResearch hermes-agent + API tersuai) | `hermes-gateway/` | Mungkin image yang sama nama **[SAHKAN-SERVER]** |
| DB memori (pgvector) | `server-b/init-memory.sql` | `staffbot-memory-db` :5434 |
| WhatsApp (Node + Baileys) | `server-b/baileys-manager/` | `staffbot-baileys` :8653 |
| Telegram (Node) | `server-b/telegram-manager/` | `staffbot-telegram` :8654 |
| Embeddings | ❌ tiada dalam repo | `staffbot-embeddings` **[SAHKAN-SERVER]** |
| Container per klien | `server-b/core-image/` atau `sandbox/` | `staffbot-{client_id}` :9xxx |
| Web UI (HTML + Tailwind CDN + vanilla JS) | `api/app/static/` | dihidang oleh `staffbot-api` |

### 1.2 Istilah

| Istilah | Maksud |
| :--- | :--- |
| Client | Syarikat pelanggan, iaitu satu akaun dan satu tenant |
| AI Staff / bot | Rekod dalam jadual `containers` |
| Managed token | Kuota token yang dibayar melalui pakej, menggunakan kunci LLM milik platform |
| BYOK | Bring Your Own Key |
| Central Brain v2 | Carian memori hibrid dalam gateway |

## 2. Keperluan fungsian

### FR-AUTH: Pengesahan

| ID | Keperluan | Status | Bukti / nota |
| :--- | :--- | :--- | :--- |
| FR-AUTH-1 | Daftar akaun (status `pending`, rizab subdomain, cipta subscription) | ✅ | `routers/auth.py:28` |
| FR-AUTH-2 | Login email + password, pulangkan JWT | ✅ | `auth.py:119`. Gunakan HS256, tamat dalam 24 jam, claim `sub`, `role`, `client_id` |
| FR-AUTH-3 | Tukar password | ✅ | `auth.py:164` |
| FR-AUTH-4 | Refresh token / logout di server | ❌ | Token hanya dipadam dari localStorage |
| FR-AUTH-5 | Admin dikenal pasti | ⚠️ | Hanya melalui perbandingan email (`middleware/auth.py:53-66`), bukan dari claim `role` |
| FR-AUTH-6 | Had cubaan login (brute force) | ❌ | `rate_limit.py` wujud tetapi tidak digunakan di mana-mana |
| FR-AUTH-7 | Gantung akaun (`suspended`) | ✅ | Pengguna digantung mendapat respons 403 |

### FR-BILL: Pakej, bayaran, kuota

| ID | Keperluan | Status | Nota |
| :--- | :--- | :--- | :--- |
| FR-BILL-1 | CRUD pakej (admin) | ⚠️ | Router memanggil lajur `memory_retention_days`/`memory_item_limit` yang tiada dalam model, jadi create mungkin gagal |
| FR-BILL-2 | Checkout pakej Stripe (MYR, kad + FPX) | ✅ | `subscriptions.py:26`, `services/stripe_service.py` |
| FR-BILL-3 | Webhook Stripe mengaktifkan langganan dan deploy | ✅ | `webhooks.py:30`. Hanya event `checkout.session.completed` |
| FR-BILL-4 | Pembaharuan bulanan automatik | ❌ | Bayaran sekali. `managed_token_used` tidak pernah di-reset |
| FR-BILL-5 | Top-up token | ✅ | `billing.py:46`; webhook menambah kuota |
| FR-BILL-6 | Percubaan percuma | ❌ | `trial_days` hanya dipaparkan |
| FR-BILL-7 | Kuota per penyedia (`package_providers.token_quota`) | ❌ | Disimpan tetapi tidak dikuatkuasakan |
| FR-BILL-8 | Affiliate: klik, rujukan, bayaran | ⚠️ | Komisen tidak pernah dicipta secara automatik; `/affiliates/convert` terbuka tanpa auth |

### FR-PROV: Provisioning

| ID | Keperluan | Status | Nota |
| :--- | :--- | :--- | :--- |
| FR-PROV-1 | Jana subdomain | ✅ | `deployment_service.py:31-40` |
| FR-PROV-2 | Rekod DNS Cloudflare | ⚠️ **Bug** | Nilai A-record diberi `staffbot.my`, bukan IP (`deployment_service.py:57`). Mungkin digantikan oleh rekod wildcard **[SAHKAN-SERVER]** |
| FR-PROV-3 | Container per klien dengan had CPU/RAM | ✅ | `docker_service.py:125-259`. Ada hardening: cap_drop ALL, read-only, had PID |
| FR-PROV-4 | Had storan | ❌ | Hanya dihantar sebagai env var |
| FR-PROV-5 | Nginx map subdomain → port | ⚠️ | Menulis `/etc/nginx/ssl/subdomain_ports.map`; reload bergantung pada cron host yang tiada dalam repo **[SAHKAN-SERVER]** |
| FR-PROV-6 | "Apply" had pakej pada container sedia ada | ❌ | `apply_container_limits` tidak mengubah apa-apa |
| FR-PROV-7 | Buang DNS dan nginx map bila container dipadam | ❌ | |

### FR-CHAT: Chat AI

| ID | Keperluan | Status | Nota |
| :--- | :--- | :--- | :--- |
| FR-CHAT-1 | Hantar mesej dan dapat jawapan | ✅ | `chat.py:176` → gateway `/v1/chat/completions` |
| FR-CHAT-2 | Semak kuota sebelum panggil LLM | ✅ | `chat.py:208-242` |
| FR-CHAT-3 | Guna BYOK yang disimpan | ❌ **Bug** | `is_byok` dikira tetapi diabaikan. Hanya `api_key` dalam body request yang digunakan |
| FR-CHAT-4 | Pilih penyedia: diminta → pakej → fallback DeepSeek | ✅ | `chat.py:305-351`. UI sentiasa menghantar `provider: 'mimo'` |
| FR-CHAT-5 | Moderasi sebelum LLM | ✅ | `content_moderation.py`. ⚠️ API key dihantar ke hos moderasi luar |
| FR-CHAT-6 | Suntik memori ke dalam prompt | ✅ | Top 3 memori, setiap satu 500 aksara |
| FR-CHAT-7 | Sejarah perbualan dihantar ke LLM | ❌ | Hanya system + mesej semasa |
| FR-CHAT-8 | Streaming respons | ❌ | `stream: false`, timeout 120 s |
| FR-CHAT-9 | Gelung tool ReAct (maks 3 pusingan) | ✅ | `server-b/gateway/main.py:1582-1644` |
| FR-CHAT-10 | Tolak token selepas chat | ⚠️ | Hanya token pusingan terakhir yang dikira |
| FR-CHAT-11 | Simpan mesej (`chat_messages`) | ✅ | |
| FR-CHAT-12 | Audit setiap chat | ✅ | `audit_trail`, 8 laluan |
| FR-CHAT-13 | Lampiran fail (PDF/DOCX/teks/imej, maks 10 MB) | ✅ | `chat.py:595` |
| FR-CHAT-14 | Ekstrak kandungan dari URL | ⚠️ | Tiada perlindungan SSRF |

### FR-TOOL: Tool ejen (dalam gateway)

| ID | Tool | Status | Had |
| :--- | :--- | :--- | :--- |
| FR-TOOL-1 | `search_memory`, `save_to_memory`, `get_current_time` | ✅ | — |
| FR-TOOL-2 | `call_webhook` (konfigurasi per klien, auth disulitkan) | ✅ | 10/min; blok IP dalaman (⚠️ `100.64.0.0/10` tidak diblok) |
| FR-TOOL-3 | `web_search` (DuckDuckGo/Brave/SerpAPI/Google CSE) | ✅ | 20/min |
| FR-TOOL-4 | `send_email` (SMTP klien) | ✅ | 50/hari |
| FR-TOOL-5 | `set_smtp_config` melalui chat | ✅ | ⚠️ Password SMTP melalui konteks LLM |
| FR-TOOL-6 | `create_document` | ❌ | Dirancang |
| FR-TOOL-7 | Setup webhook melalui chat | ❌ | Dirancang |
| FR-TOOL-8 | Tool tugasan | ⚠️ | Hanya pada laluan Hermes; tiada dalam gateway utama |

### FR-MEM: Memori

| ID | Keperluan | Status | Nota |
| :--- | :--- | :--- | :--- |
| FR-MEM-1 | Simpan memori | ✅ | Tanpa embedding |
| FR-MEM-2 | Carian hibrid 4 strategi + RRF | ⚠️ | Strategi "vektor" sebenarnya ILIKE; strategi "graph" terdedah kepada **SQL injection** |
| FR-MEM-3 | Embedding / carian semantik | ❌ | Tiada kod yang menjana embedding |
| FR-MEM-4 | Upload dokumen → chunks → memori | ❌ **Rosak** | `memory_service.py` dan `memory_processor.py` tiada dalam repo **[SAHKAN-SERVER]** |
| FR-MEM-5 | Klasifikasi auto (fakta/tugasan/keutamaan) | ✅ | `main.py:803` |
| FR-MEM-6 | Had memori ikut pakej, retention | ⚠️ | Lajur tiada dalam model; tiada penjadual |

### FR-CH: Saluran

| ID | Keperluan | Status | Nota |
| :--- | :--- | :--- | :--- |
| FR-CH-1 | Sesi WhatsApp melalui QR | ✅ | `baileys-manager/index.js:234` |
| FR-CH-2 | Mesej WhatsApp masuk → balasan AI | ❌ | Mesej dihantar ke container, tetapi container tiada route `/webhook/whatsapp` **[SAHKAN-SERVER]** |
| FR-CH-3 | Pulihkan sesi WhatsApp selepas restart | ❌ | |
| FR-CH-4 | Daftar webhook bot Telegram | ⚠️ | URL webhook tidak sepadan dengan route |
| FR-CH-5 | Mesej Telegram masuk → balasan AI | ❌ | Sama seperti FR-CH-2 |
| FR-CH-6 | Mesej suara, imej tanpa kapsyen, dokumen | ❌ | Diabaikan |
| FR-CH-7 | Notifikasi keluar (WhatsApp, email, SMS, in-app) | ✅ | `notification_service.py` |

### FR-ADM: Admin

| ID | Keperluan | Status |
| :--- | :--- | :--- |
| FR-ADM-1 | Dashboard (statistik, kesihatan, aktiviti, penggunaan token) | ✅ |
| FR-ADM-2 | CRUD pengguna (klien), deploy, padam dengan arkib `.json.gz` | ✅ |
| FR-ADM-3 | CRUD penyedia LLM, uji sambungan, assign ke pakej | ✅ |
| FR-ADM-4 | Subdomain, top-up, affiliate, tetapan | ✅ |
| FR-ADM-5 | Polisi skill/tool global | ⚠️ Tiada override per klien |
| FR-ADM-6 | Halaman `my-staff-ai`, butang `generate` dalam policy | ❌ Endpoint tidak wujud |

## 3. Keperluan bukan fungsian (keadaan sebenar)

| Kategori | Keadaan |
| :--- | :--- |
| Prestasi | Tiada pengukuran. Chat tanpa streaming, timeout 120 s |
| Keselamatan transit | Cloudflare → nginx → port 127.0.0.1 |
| Keselamatan at-rest | Fernet (AES-128-CBC + HMAC) untuk semua secret; kunci diterbitkan dengan SHA-256 dari `STAFFBOT_SECRET_KEY`; password menggunakan bcrypt |
| Pengasingan tenant | Berdasarkan `client_id` dalam query. ⚠️ Ada laluan yang membenarkan penyamaran (lihat `SECURITY_FINDINGS.md`) |
| Ketersediaan | `restart: unless-stopped`; satu server, tiada failover |
| Migrasi DB | ❌ Tiada Alembic. `create_all()` + SQL manual |
| Backup | Tiada dalam repo **[SAHKAN-SERVER]** |
| Pemantauan | Hanya endpoint `/health` |
| Ujian automatik | ❌ Tiada test suite; ada beberapa skrip ujian manual dalam `scripts/` |

## 4. Kekangan

- Satu server OVH dikongsi dengan pandaibot dan mail server.
- Container API memasang `/var/run/docker.sock`, jadi ia ada akses root ke host.
- Konfigurasi runtime penting disimpan dalam jadual `settings`: kunci Stripe dan `governance_policy`.
