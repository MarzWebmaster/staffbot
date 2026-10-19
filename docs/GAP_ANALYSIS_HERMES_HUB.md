# Analisis Jurang — StaffBot.my vs PRD v2 (Enterprise Hermes Hub)

> 19 Okt 2026. Membandingkan kod StaffBot sebenar dengan `HERMES_VOICE_PROJECT_BRIEF.md` (Bahagian 3, PRD v2).
> Status: ✅ ada · ⚠️ separa · ❌ tiada.

## 1. Jawapan ringkas: boleh match?

**Boleh, tetapi separa sahaja.** StaffBot sesuai dijadikan **asas backend**. Lebih kurang **25–30%** PRD v2 sudah ada atau hampir ada. Sebahagian besar teras PRD v2 belum wujud:

- staf dalam syarikat
- RBAC
- cawangan dan jabatan
- kelulusan
- suara
- mobile
- RAG dokumen
- streaming

**Yang memang match:**
- Konsep tenant: `clients` ialah syarikat.
- Penyulitan kunci API, penyedia LLM ikut pakej, dan BYOK.
- Gateway AI dengan gelung tool (ReAct), sudah serupa dengan corak "tool + MCP".
- Audit trail, log penggunaan token, Stripe, dan panel admin.

**Yang tidak match:** daripada 21 keperluan fungsian PRD v2, hanya 1 lengkap; 10 separa dan 10 tiada langsung (lihat §3).

**Satu berita baik untuk reka bentuk.** Brief menganggap "satu container untuk satu klien yang ada ejen". Sebenarnya **semua AI berjalan dalam satu gateway berkongsi**, dan tenant dikenal pasti melalui `client_id`. Ini **memudahkan** PRD v2 (soalan C7): jadual tenant boleh kekal dalam satu DB pusat, dan mobile/web memanggil satu API yang sama.

## 2. Pemetaan konsep

| PRD v2 | StaffBot sekarang | Padanan |
| :--- | :--- | :--- |
| `tenants` | `clients` (+ `subdomains`, `subscriptions`) | ⚠️ Boleh guna `clients` sebagai tenant. Perlu tambah `tenant_code` dan `data_retention_days` |
| `users` (staf dalam tenant) | ❌ Login = `clients` itu sendiri | ❌ Perlu jadual baharu `users` dengan `client_id` |
| `branches`, `departments` | ❌ | ❌ |
| Peranan SUPER_ADMIN / TENANT_ADMIN / MANAGER / STAFF | Admin = email tertentu; pelanggan = pemilik syarikat | ❌ Perlu lajur `role` + middleware |
| `tenant_agent_config` (kunci default syarikat) | `llm_providers` (platform) + `api_keys` (BYOK per klien) | ⚠️ `api_keys` hampir sama, tetapi BYOK tidak digunakan dalam chat (bug B-03) |
| `user_agent_credentials` (kunci per staf) | ❌ | ❌ |
| `refresh_tokens` | ❌ JWT 24 jam sahaja | ❌ |
| `sop_documents` + `sop_chunks` (RAG) | `client_memory` dengan chunk (`parent_id`, `chunk_index`) + `vector(1536)`, tetapi tiada embedding dijana | ⚠️ Struktur hampir ada, enjin belum |
| `ai_agents` (per jabatan) | `containers` ("AI Staff": nama, skill, tool) | ⚠️ Boleh dilanjutkan dengan `department_id`, `system_prompt`, `model` |
| `role_tool_permissions` | Polisi global + kategori tool per pakej | ⚠️ Per pakej, bukan per peranan |
| `approvals` | ❌ | ❌ |
| `chat_sessions` / `chat_messages` | `chat_messages` sahaja (tiada sesi) | ⚠️ Tambah `chat_sessions` |
| `device_tokens` | ❌ | ❌ |
| `usage_logs` | `token_usage_log` + `subscriptions.managed_token_used` | ⚠️ Tiada `user_id`, minit audio, atau `key_source` |
| `audit_logs` | `audit_trail` | ✅ Tambah `user_id`, `branch_id` |
| PK UUID | PK integer | ⚠️ **Cadangan: kekalkan integer** supaya konsisten dengan skema sedia ada |

## 3. Keperluan fungsian PRD v2 vs StaffBot

### Fasa 1 — MVP

| ID | Keperluan | Status | Di mana / apa perlu dibuat |
| :--- | :--- | :--- | :--- |
| F1.1 | Login (kod syarikat/subdomain + email + password), JWT dengan `user_id`/`tenant_id`/`branch_id`/`role`, access 15 min, refresh 30 hari | ⚠️ | Login ada (`auth.py`), tetapi untuk `clients` sahaja. Perlu jadual `users`, claim baharu, refresh token |
| F1.2 | Pengurusan tenant (portal pusat) | ✅ | Admin users/subdomains/packages. Tambah `tenant_code` |
| F1.3 | CRUD cawangan, jabatan, staf + jemputan email | ❌ | Baharu |
| F1.4 | Kunci API syarikat (disulitkan, 4 aksara akhir, uji sambungan) | ⚠️ | `api_keys` + `toggle-byok` (ada `key_prefix`). Uji sambungan hanya ada untuk penyedia admin. **Betulkan B-03 supaya BYOK benar-benar digunakan** |
| F1.5 | Kunci API per staf + resolusi staf → syarikat → terurus | ❌ | Bergantung pada `users`. Logik resolusi boleh diletakkan dalam `chat.py:305` |
| F1.6 | Chat teks, streaming, sesi, konteks cawangan/jabatan | ⚠️ | Chat ada; **tiada streaming, tiada sesi, tiada sejarah dihantar ke LLM** |
| F1.7 | Push-to-talk (< 3 s untuk audio 10 s) | ❌ | Baharu: `POST /voice/transcribe` (Whisper) |
| F1.8 | Upload SOP → chunks → embedding → RAG, dengan petikan | ⚠️ | Endpoint `/memory/upload` ada tetapi modul hilang; tiada embedding. Perlu servis embedding + carian vektor sebenar |
| F1.9 | Log audit (login, konfigurasi, setiap tool call) | ⚠️ | Chat dan tool (webhook/search/email) diaudit. Login dan perubahan konfigurasi belum |
| F1.10 | Rekod penggunaan per user dan tenant | ⚠️ | Per tenant sahaja |

### Fasa 2 — Suara

| ID | Keperluan | Status |
| :--- | :--- | :--- |
| F2.1 | TTS | ❌ |
| F2.2 | WebSocket voice stream | ❌ Tiada WebSocket langsung |
| F2.3 | Wake word | ❌ |
| F2.4 | Android foreground service | ❌ Tiada mobile app |
| F2.5 | Push notification | ❌ Ada notifikasi WhatsApp/email/in-app, tetapi tiada FCM/APNs |

### Fasa 3 — Enterprise

| ID | Keperluan | Status | Nota |
| :--- | :--- | :--- | :--- |
| F3.1 | Aliran kelulusan | ❌ | Gateway ReAct boleh "pintas" tool sensitif dan cipta baris `approvals` |
| F3.2 | Kebenaran tool per peranan | ⚠️ | Ada penguatkuasaan per pakej (`EnforcementService`), tetapi hanya sebagai teks prompt. Perlu dikuatkuasakan dalam `_execute_tool` |
| F3.3 | Ejen per jabatan | ⚠️ | `containers` = bot; tambah jabatan dan prompt |
| F3.4 | Integrasi MCP (ERPNext) | ⚠️ | Tiada MCP, tetapi `call_webhook` boleh memanggil REST API ERPNext. Ini laluan cepat sebelum MCP |
| F3.5 | Dashboard laporan + CSV | ⚠️ | Dashboard admin ada; laporan per cawangan tiada |
| F3.6 | Speaker verification | ❌ | |

**Ringkasan kiraan (21 keperluan):** ✅ 1 · ⚠️ 10 · ❌ 10.

## 4. Seni bina — cadangan C1–C9 vs realiti

| # | Cadangan brief | Realiti StaffBot | Keputusan dicadangkan |
| :--- | :--- | :--- | :--- |
| C1 | `tenants` dalam DB backend sahaja | `clients` dalam `staffbot_db` | ✅ Guna `clients` sebagai tenant |
| C2 | JWT dengan `user_id` + `tenant_id` | JWT dengan `sub` = email + `client_id` | Lanjutkan: tambah `user_id`, `role`, `branch_id` |
| C3 | Kunci tidak pernah dihantar ke app | Kunci dinyahsulit di API dan dihantar ke gateway dalaman sahaja | ✅ Sudah dipatuhi (kecuali isu S-06) |
| C4 | AES-256-GCM | Fernet (AES-128-CBC + HMAC) | Fernet cukup selamat. Keutamaan lebih tinggi: pisahkan kunci JWT dan kunci penyulitan, tambah versi kunci |
| C5 | Resolusi staf → syarikat → terurus | BYOK request → terurus (BYOK yang disimpan diabaikan) | Laksanakan di `chat.py:305` |
| C6 | Kod syarikat / subdomain semasa login | Subdomain disimpan; email unik global | Email dalam `users` unik per `client_id` |
| C7 | Jadual tenant di portal pusat jika model satu container satu klien | **Bukan model satu container satu ejen**; gateway berkongsi | ✅ Satu DB pusat. Tidak perlu tenant dalam container |
| C8 | Lanjutkan StaffBot | — | ✅ **Disokong**, dengan syarat isu keselamatan kritikal dibetulkan dahulu |
| C9 | Flutter + FastAPI | API sudah FastAPI | ✅ Modul suara boleh jadi router baharu dalam API, atau servis berasingan untuk WebSocket |

## 5. Jawapan soalan S1–S9

| # | Soalan | Jawapan |
| :--- | :--- | :--- |
| S1 | Server StaffBot? | OVH ("OVH 2", `mail.pandaibot.my`), Tailscale `ovh-staffbot`. Dikongsi dengan pandaibot dan mail server |
| S2 | Ciri tambahan untuk semua klien, atau produk berasingan? | **Perlu keputusan Remy.** Teknikalnya, kedua-duanya boleh dengan satu backend; boleh dijadikan pakej "Enterprise" |
| S3 | Siapa masukkan API key staf? | Perlu keputusan Remy. Kod sekarang: pelanggan sendiri (BYOK) dan admin (penyedia platform) |
| S4 | "API ejen" = penyedia LLM atau endpoint Hermes? | Dalam kod: **API penyedia LLM** (serasi OpenAI, `base_url` + key). Jadual `llm_providers` sudah menyokong `base_url` tersuai, jadi endpoint Hermes juga boleh dimasukkan |
| S5 | iOS dalam MVP? | Perlu keputusan Remy (cadangan: Android dahulu) |
| S6 | STT/TTS cloud atau self-host? | Perlu keputusan Remy. Server OVH sudah sibuk (dikongsi), jadi cloud lebih selamat untuk MVP |
| S7 | Harga | Perlu keputusan Remy. Pakej sedia ada: RM49/149/499 |
| S8 | Klien pilot | Perlu keputusan Remy |
| S9 | ERP pertama | ERPNext. Boleh bermula dengan `call_webhook` ke REST API ERPNext tanpa perlu MCP |

## 6. Prasyarat sebelum membina PRD v2

1. **Betulkan isu keselamatan kritikal S-01 hingga S-06** (`SECURITY_FINDINGS.md`). PRD v2 menambah lebih ramai pengguna, jadi permukaan serangan bertambah.
2. **Sahkan di server** perkara yang ditanda [SAHKAN-SERVER] (`SERVER_VERIFICATION.md`), terutamanya:
   - image `staffbot-gateway` yang live;
   - `staffbot-embeddings`;
   - modul memori yang hilang;
   - status balasan WhatsApp.
3. **Tambah migrasi DB (Alembic)**. PRD v2 menambah sekitar 10 jadual; `create_all` + `psql` manual tidak cukup selamat.
4. **Persekitaran staging.** Server production dikongsi dengan sistem lain.

## 7. Cadangan urutan pembinaan (dipinda dari brief §4.4)

1. Pembetulan keselamatan + Alembic + staging.
2. `users` (bawah `clients`), `role`, `branches`, `departments`; JWT baharu + refresh token.
3. Resolusi kunci staf → syarikat → terurus (betulkan BYOK).
4. `chat_sessions` + sejarah perbualan ke LLM + **streaming SSE** dari gateway.
5. Servis embedding + `sop_chunks` (atau guna semula `client_memory`) + carian vektor sebenar.
6. `POST /voice/transcribe` (Whisper API); uji rakaman BM/Manglish.
7. `role_tool_permissions` dikuatkuasakan dalam `_execute_tool` + `approvals`.
8. Web admin (cawangan/jabatan/staf/SOP) + chat push-to-talk.
9. Flutter Android: login, chat, push-to-talk, kelulusan.
10. Fasa 2 (TTS, WebSocket, wake word) dan Fasa 3 (ERPNext, laporan).
