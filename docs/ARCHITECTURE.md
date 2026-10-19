# Seni Bina Sistem — StaffBot.my

> Dikemas kini 19 Okt 2026 berdasarkan kod repo. **[SAHKAN-SERVER]** menandakan perkara yang perlu disemak di server.

## 1. Topologi

Semuanya berjalan dalam **satu server OVH** ("OVH 2", hostname `mail.pandaibot.my`). Server ini juga menjalankan pandaibot (PHP, scheduler, Redis, MySQL) dan mail server (Postfix/Dovecot). Akses admin dibuat melalui SSH dalam Tailscale sahaja (node `ovh-staffbot`).

IP server, port SSH dan credential **tidak disimpan dalam repo ini**. Simpan dalam password manager.

```
Internet
   │
Cloudflare (DNS + CDN, *.staffbot.my)
   │
nginx (/etc/nginx/conf.d/, cert staffbot + wildcard)
   ├── staffbot.my, api.staffbot.my ──► staffbot-api :8000   (FastAPI + web UI statik)
   ├── <sub>.staffbot.my ──(map subdomain_ports.map)──► staffbot-{id} :9xxx  (container klien)
   └── /office/ ──► Agent Office :3334  [SAHKAN-SERVER]

Rangkaian Docker dalaman (port semua diikat ke 127.0.0.1)
   staffbot-api ──► staffbot-gateway :8080 ──► penyedia LLM luar (DeepSeek/OpenRouter/…)
        │                 │
        ├──► staffbot-db :5433 (staffbot_db) ◄──┘
        │
   staffbot-baileys :8653 ◄──► staffbot-gateway
   staffbot-telegram :8654 ◄──► staffbot-gateway
   staffbot-memory-db :5434 (staffbot_memory)        [mungkin laluan lama]
   staffbot-embeddings                               [tiada dalam repo — SAHKAN-SERVER]
```

## 2. Komponen

| Komponen | Kod | Peranan |
| :--- | :--- | :--- |
| **staffbot-api** | `api/app/` | Auth, billing (Stripe), provisioning container, CRUD, chat API, web UI statik, admin. Container ini mount `docker.sock` |
| **staffbot-gateway** | `server-b/gateway/main.py` (kemungkinan besar), **atau** `hermes-gateway/` **[SAHKAN-SERVER]** | Proksi LLM serasi OpenAI (`/v1/chat/completions`), gelung tool ReAct, memori (Central Brain v2), kawalan Docker, penghala WhatsApp/Telegram |
| **Hermes Agent** | `hermes-gateway/`, `hermes-core/` | NousResearch hermes-agent dengan toolset `staffbot`. Chat web **pernah** guna Hermes :8642 (3 Jun 2026), kemudian **beralih semula** ke gateway :8080 (15 Jun 2026). Sekarang Hermes tidak berada dalam laluan chat utama |
| **Container klien** | `server-b/core-image/` atau `sandbox/` **[SAHKAN-SERVER]** | Satu bagi setiap klien (`staffbot-{id}`). **Tiada ejen AI di dalamnya.** Ia hanya proksi `/chat` ke gateway, atau executor shell/python |
| **baileys-manager** | Node 20 + Baileys | Sesi WhatsApp per klien (QR), hantar dan terima mesej |
| **telegram-manager** | Node 20 | Webhook bot Telegram per klien |
| **hybrid-brain** | `server-b/hybrid-brain/` | Prototaip (Hindsight). Tiada dalam compose dan tiada yang memanggilnya |

## 3. Aliran chat web (laluan utama)

```
Pelayar (chat.html)
  │ POST /api/v1/chat/send  {content, container_id, provider:'mimo', image_base64?}
  ▼
staffbot-api  (routers/chat.py)
  1. JWT → client
  2. Semak kuota (subscriptions.managed_token_quota/used)
  3. EnforcementService → senarai skill/tool yang dibenarkan (pakej ∩ polisi global)
  4. Simpan mesej user → chat_messages
  5. Moderasi 3 lapis (regex → klasifikasi AI luar → jejak perbualan)
  6. POST gateway /api/memory/search (top 3)
  7. Bina system prompt (gaya BM/EN + skill/tool + memori)
  8. Pilih penyedia: diminta → pakej → "deepseek-pchp17"; nyahsulit kunci penyedia
  9. POST gateway /v1/chat/completions  (Bearer, + client_id, api_key, base_url)
  ▼
staffbot-gateway  (server-b/gateway/main.py)
  - Gelung ReAct ≤ 3 pusingan dengan tool:
    search_memory · save_to_memory · get_current_time · call_webhook · web_search · send_email · set_smtp_config
  - Panggil {base_url}/chat/completions penyedia LLM (stream: false)
  - Tulis token_usage_log
  ▼
staffbot-api
 10. Simpan jawapan → chat_messages
 11. BackgroundTask: gateway /api/memory/classify-and-save (fakta → memori, tugasan → tasks)
 12. Tolak token dari kuota; tulis audit_trail
```

Nota:
- Sejarah perbualan **tidak** dihantar ke LLM.
- Tiada streaming.
- SOUL/persona Hermes tidak digunakan dalam laluan ini; system prompt dibina sendiri dalam `chat.py`.

## 4. Aliran WhatsApp / Telegram (dalam kod sekarang)

```
WhatsApp → baileys-manager (sesi client_id) → gateway /api/incoming/whatsapp/{cid}
         → container klien http://host.docker.internal:{port}/webhook/whatsapp
```

⚠️ Container klien (`core-image/agent.py`, `sandbox/agent.py`) **tiada** route `/webhook/whatsapp` atau `/webhook/telegram`. Dalam kod yang di-commit, balasan AI automatik untuk mesej masuk **tidak lengkap**. **[SAHKAN-SERVER]** Uji dengan menghantar mesej WhatsApp ke bot klien.

Telegram mengikut aliran yang sama. Arahan `/connect <token>` dikendalikan oleh gateway.

## 5. Central Brain v2 (memori)

- **Storan**: jadual `client_memory`, dengan `embedding vector(1536)` dan indeks HNSW.
- **Carian**: 4 strategi digabungkan dengan Reciprocal Rank Fusion (k=60):
  1. "Vector": ⚠️ sebenarnya jatuh ke ILIKE, kerana teks dihantar sebagai vektor dan tiada embedding dijana.
  2. Keyword: `to_tsvector('simple')`.
  3. Temporal: `created_at DESC`.
  4. "Graph": padanan kata kunci. ⚠️ Query dibina dengan f-string, jadi terdedah kepada SQL injection.
- Reranker cross-encoder: dimatikan (`RERANKER_MODEL` kosong).
- **Embedding: tiada kod yang menjananya.** Modul `memory_service.py` dan `memory_processor.py` yang diimport oleh API tiada dalam repo. Servis `staffbot-embeddings` di server mungkin mengisi jurang ini **[SAHKAN-SERVER]**.

## 6. Provisioning klien baharu

1. Pencetus: webhook Stripe, admin "deploy", atau pelanggan cipta bot.
2. `DeploymentService`:
   1. Jana subdomain.
   2. Cipta rekod A di Cloudflare. ⚠️ Rosak, diberi nama domain.
   3. `DockerService` jalankan `staffbot-{id}`:
      - image `staffbot-core:latest`, port rawak pada 127.0.0.1;
      - volume `/root/staffbot/containers/staffbot-{id}` → `/app/data`;
      - cap_drop ALL, read-only, had PID 100, had CPU/RAM.
   4. Tulis baris dalam `/etc/nginx/ssl/subdomain_ports.map`. Cron host reload nginx **[SAHKAN-SERVER]**.
   5. Sahkan (DNS, port, HTTPS, gateway).
   6. Hantar notifikasi WhatsApp/email/in-app.
3. ⚠️ Container klien diberi `GATEWAY_AUTH_KEY`, iaitu **kunci induk gateway**. Lihat `SECURITY_FINDINGS.md` S-05.

## 7. Skill dan polisi

- Katalog: 788 skill + toolset dalam `api/app/routers/admin/policy.py`, disalin ke `skills_registry`.
- Penguatkuasaan: (kategori skill/tool pakej) ∩ (`settings.governance_policy` global).
- Hasilnya **hanya disenaraikan sebagai teks dalam system prompt**. Tiada kod skill yang dijalankan dalam laluan chat sekarang.

## 8. Sejarah ringkas (dari git)

| Tarikh | Perubahan |
| :--- | :--- |
| 3 Jun 2026 | Toolset StaffBot untuk Hermes; chat dipindah ke Hermes Native :8642; vision ke Mimo |
| 6–7 Jun 2026 | UI mobile-responsive; moderasi 3 lapis; Agent Office |
| 15 Jun 2026 | Chat **kembali** ke gateway tersuai :8080; ReAct loop; klasifikasi memori; audit trail |
| 16 Jun 2026 | Tool `call_webhook`, `web_search`, `send_email`, `set_smtp_config` |
| 26–27 Jun 2026 | Audit kod dan pembetulan bug (4 batch) |
| Okt 2026 | Server dipindah ke OVH (dahulu Tencent + Contabo) |
