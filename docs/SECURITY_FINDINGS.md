# Penemuan Keselamatan dan Bug — StaffBot.my

> Semakan kod (baca sahaja), 19 Okt 2026. Tiada ujian dijalankan pada sistem live.
> Nilai rahsia sengaja **tidak** ditulis di sini.
> Keutamaan: 🔴 Kritikal (betulkan segera) · 🟠 Tinggi · 🟡 Sederhana.

## Status pembetulan

S-01 hingga S-06 (✅) **sudah dibetulkan di branch `claude/staffbot-my-review-i3w7be`**, 19 Okt 2026, dan diuji (28 ujian lulus). **Belum di-deploy ke production.** Langkah deploy ada di §Deploy di bawah.

## 🔴 Kritikal

| ID | Isu | Lokasi | Kesan | Cadangan |
| :--- | :--- | :--- | :--- | :--- |
| S-01 ✅ | Endpoint tetapkan penggunaan token **tanpa auth** | `routers/subscriptions.py:86` `PUT /subscriptions/{id}/tokens` | Sesiapa boleh reset kuota mana-mana klien, iaitu chat percuma tanpa had | Tambah auth dalaman (`verify_internal`), atau buang endpoint ini |
| S-02 ✅ | Pelanggan boleh tukar `package`, `status` dan `email` sendiri | `routers/clients.py:91` + `schemas/client.py:38-45` | Naik taraf pakej tanpa bayar; aktifkan akaun sendiri; mungkin ambil alih email admin jika akaun admin belum wujud | Hadkan `ClientUpdate` kepada name/company/phone sahaja |
| S-03 ✅ | Kunci dalaman (`X-Internal-Key`) ada **nilai default hardcoded**, dan nama env var tidak sepadan (`GATEWAY_API_KEY` dalam kod, `STAFFBOT_GATEWAY_API_KEY` dalam compose) | `middleware/auth.py:13`, `69-102` | Sesiapa yang tahu nilai default boleh menyamar sebagai mana-mana klien pada `/tasks/*`, `/chat/upload`, `/chat/extract-link` | Buang default; gagal tertutup jika tidak ditetapkan; betulkan nama env |
| S-04 ✅ | **SQL injection** dalam carian memori "graph" (kata kunci dimasukkan dengan f-string) | `server-b/gateway/main.py:667-673` | Mesej chat boleh memintas penapis `client_id`, jadi **memori tenant lain** boleh bocor ke dalam prompt | Guna parameter bind (`$n`) |
| S-05 ✅ | Kunci induk gateway (`AUTH_KEY`) disuntik ke **setiap container klien** | `docker_service.py:154`, `gateway/main.py:276` | Jika satu container dicerobohi, penyerang boleh baca memori semua klien dan start/stop/padam **mana-mana container** di host (nama tidak disahkan). Gateway ada `docker.sock`, jadi ini bermakna akses root host | Token berasingan per klien; whitelist nama container `staffbot-*` |
| S-06 ✅ | API key pengguna (BYOK) atau kunci Hermes dihantar ke **hos moderasi luar** (Tailscale funnel) | `services/content_moderation.py:28`, `chat.py:272` | Kunci pelanggan bocor ke pihak ketiga atau hos peribadi | Guna kunci moderasi khusus milik platform |

## 🟠 Tinggi

| ID | Isu | Lokasi | Cadangan |
| :--- | :--- | :--- | :--- |
| S-07 | SSRF penuh pada `/chat/extract-link` (tiada tapisan IP, `follow_redirects=True`) | `chat.py:666-745` | Guna semula penapis IP dari `call_webhook` dan matikan redirect |
| S-08 | Penapis SSRF `call_webhook` tidak meliputi `100.64.0.0/10` (rangkaian Tailscale) dan `0.0.0.0/8`; DNS gagal dianggap lulus | `gateway/main.py:1021-1035` | Tambah julat itu; gagal tertutup |
| S-09 | Container klien mungkin mendedahkan `/chat`, `/memory/recent` atau `/exec` (shell) **tanpa auth** melalui subdomain klien | `core-image/agent.py`, `sandbox/agent.py` **[SAHKAN-SERVER]** | Semak image `staffbot-core` yang live; tambah auth |
| S-10 | Tool Hermes membenarkan LLM mengisi `client_id` sendiri | `hermes-gateway/tools/*.py` | Ambil `client_id` dari konteks sesi, bukan dari LLM |
| S-11 | Endpoint `hermes-gateway/gateway_api.py` tanpa auth (`/api/chat/send`, `/admin/reload-profile*`); `recreate_containers.py` publish port 8080/8642 pada semua interface | — | Tambah auth; ikat ke 127.0.0.1 |
| S-12 | baileys/telegram manager tanpa auth; `auth_path` WhatsApp dikawal pemanggil (cipta dan padam direktori sesuka hati) | `baileys-manager/index.js:66,320` | Auth + validasi path |
| S-13 | Webhook status gateway lulus jika `SERVER_B_API_KEY` kosong | `webhooks.py:254` | Gagal tertutup |
| S-14 | `/affiliates/convert` awam: sesiapa boleh kaitkan klien dengan affiliate | `affiliates.py:628` | Panggil secara dalaman sahaja semasa daftar |
| S-15 | Tiada had cubaan login | `rate_limit.py` tidak digunakan | Pasang rate limit (Redis) pada login/register |
| S-16 | Default password/kunci hardcoded dalam beberapa fail, termasuk fail `.bak`, skrip seed (password admin dicetak) dan skrip ujian | Lihat `DATABASE.md` dan laporan audit | Buang semua default; putar kunci yang pernah di-commit |
| S-17 | IP server, port SSH dan path SSH key pernah di-commit dalam `docs/` | Sejarah git | Anggap ia terdedah; putar kunci SSH lama |

## 🟡 Sederhana

| ID | Isu | Lokasi |
| :--- | :--- | :--- |
| S-18 | `GET /admin/settings` memulangkan kunci Stripe dalam bentuk nyahsulit | `admin/settings.py:19` |
| S-19 | Satu `SECRET_KEY` untuk JWT **dan** penyulitan, tanpa rotasi; KDF hanya SHA-256 | `utils/encryption.py` |
| S-20 | Password SMTP melalui konteks LLM (`set_smtp_config`) | `gateway/main.py:1462` |
| S-21 | Kunci penyedia LLM dalam bentuk teks biasa dalam `/app/data/config.yaml` (hermes) | `gateway_api.py:378` |
| S-22 | Maklumat bank affiliate tidak disulitkan | `affiliate_payouts.account_details` |
| S-23 | CORS `*` pada gateway | `gateway/main.py`, `gateway_api.py` |
| S-24 | Server dikongsi dengan pandaibot dan mail server; SSH guna password | Infra |

## Bug fungsian utama

| ID | Bug | Lokasi |
| :--- | :--- | :--- |
| B-01 | Modul `memory_service.py` dan `memory_processor.py` tiada, jadi endpoint `/memory/*` akan gagal | `routers/memory.py` **[SAHKAN-SERVER]** |
| B-02 | Tiada embedding dijana, jadi carian "vektor" tidak berfungsi | gateway |
| B-03 | BYOK yang disimpan tidak digunakan; laluan BYOK boleh crash (`UnboundLocalError`) jika `model` tiada | `chat.py:190-205, 361` |
| B-04 | Rekod DNS Cloudflare diberi `staffbot.my`, bukan IP | `deployment_service.py:57` |
| B-05 | Padam satu bot akan membuang container yang dikongsi oleh semua bot klien | `routers/containers.py:301` |
| B-06 | `managed_token_used` tidak pernah di-reset, jadi pembelian semula tidak menambah token | `webhooks.py` |
| B-07 | Pusingan tool tidak dikira sepenuhnya dalam kuota | `gateway/main.py` / `chat.py:456` |
| B-08 | Balasan AI WhatsApp/Telegram tidak lengkap (container tiada route webhook) | `core-image/agent.py` **[SAHKAN-SERVER]** |
| B-09 | Token bot Telegram hilang bila servis restart; sesi WhatsApp tidak dipulihkan | managers |
| B-10 | Komisen affiliate tidak pernah dicipta | `affiliates.py` |
| B-11 | Lajur pakej `memory_*` tiada dalam model | `admin/packages.py:110` |
| B-12 | Nama pakej tidak konsisten: seed `starter/professional`, daftar `basic`, gateway `trial/basic/pro/business` | pelbagai |
| B-13 | `provider_token_usage` (JSON) diubah in-place tanpa `flag_modified`, jadi mungkin tidak disimpan | `chat.py:465` |
| B-14 | UI memanggil endpoint yang tidak wujud: `/admin/staff`, `/admin/policy/*/generate` | static/admin |
| B-15 | `send_email` audit tidak pernah ditulis (coroutine tidak di-await) | `gateway/main.py:1433` |
| B-16 | Moderasi `ConversationTracker` dan cache Stripe disimpan dalam memori per worker (2 worker) | `content_moderation.py`, `stripe_service.py` |

## Tindakan segera dicadangkan (urutan)

1. Tukar password `ubuntu` di server OVH dan beralih ke SSH key (S-24).
2. Betulkan S-01, S-02, S-03 dan S-13. Setiap satu pembetulan kecil, tidak lebih dari beberapa baris.
3. Betulkan S-04 (SQL injection), menggunakan parameter bind.
4. Putar `AUTH_KEY` gateway dan semua kunci default; buang default dari kod (S-05, S-16).
5. Tukar kunci moderasi (S-06).
6. Tambah penapis SSRF pada `extract-link` (S-07, S-08).

## Deploy pembetulan S-01 hingga S-06

1. **Env var** (dalam `.env` di server):
   - `STAFFBOT_GATEWAY_API_KEY` mesti ditetapkan, dan nilainya sama dengan `GATEWAY_API_KEY` dalam container Hermes gateway (jika tool Hermes digunakan). Nilai default lama dalam kod sudah dibuang, jadi jika ia tidak ditetapkan, tool Hermes (`/tasks/*`, `/chat/upload`) akan ditolak.
   - `STAFFBOT_SERVER_B_API_KEY` mesti sama dengan `GATEWAY_AUTH_KEY` (AUTH_KEY gateway).
   - Pilihan: `MODERATION_API_KEY`. Jika kosong, `HERMES_API_KEY` digunakan.
2. **Rebuild** `staffbot-api` dan `staffbot-gateway`.
3. **Cipta semula container klien** supaya kunci induk lama dalam env mereka diganti dengan token per klien. Container sedia ada masih berfungsi dengan kunci lama, tetapi risiko S-05 kekal sehingga ia dicipta semula.
4. **Putar `GATEWAY_AUTH_KEY`**, kerana kunci induk lama sudah berada dalam setiap container klien.
5. Perubahan tingkah laku untuk pengguna:
   - pelanggan tidak lagi boleh menukar email sendiri di halaman Settings (medan kini read-only; tukar melalui admin);
   - moderasi pengguna BYOK kini menggunakan kunci platform.

## Status selepas pembinaan Managed Hermes (23 Okt 2026, belum deploy)

| ID | Status | Nota |
| :--- | :--- | :--- |
| B-03 | ✅ dalam laluan baharu | LLM proxy benar-benar menggunakan BYOK yang disimpan (jika pakej membenarkan). Laluan chat lama (`routers/chat.py`) belum diubah dan akan dibuang selepas migrasi |
| B-07 | ✅ dalam laluan baharu | Proxy mengira token **setiap pusingan** ejen |
| B-08 | ✅ dalam laluan baharu | Channel router menghantar mesej WhatsApp/Telegram ke Hermes pelanggan dan membalas |
| B-11 | ✅ | Create pakej dibetulkan; lajur ditambah melalui Alembic |
| — | ✅ | Setup WhatsApp/Telegram dahulu memanggil route gateway yang tidak wujud; kini memanggil pengurus terus |
| S-07/S-08 | ✅ untuk tool baharu | `staffbot_call_webhook` blok semua alamat bukan awam (termasuk `100.64/10`), DNS gagal = tolak, tiada redirect. `/chat/extract-link` lama masih belum dibetulkan |

**Pertimbangan keselamatan reka bentuk baharu:**
- Pelanggan yang ada shell (Web Console atau `!cmd` dalam CLI Hermes) boleh membaca token proxy mereka sendiri dalam `/etc/hermes/.env`. Ini **dijangka**: token hanya membenarkan kuota pelanggan itu sendiri, dan semua had dikuatkuasakan di proxy.
- Semakan SSRF webhook ada tetingkap DNS rebinding (alamat disemak, kemudian httpx resolve semula). Risiko rendah kerana firewall host juga menyekat rangkaian dalaman dari API. Boleh diperketatkan dengan sambung terus ke IP yang disemak.
- Keupayaan (capabilities) container `CHOWN, SETUID, SETGID, DAC_OVERRIDE, FOWNER, KILL` dikekalkan untuk boot s6 imej Hermes. **[UJI-STAGING]** cuba buang `DAC_OVERRIDE`/`FOWNER`/`KILL` jika imej masih boot.
- Firewall bergantung pada `iptables` dan rantai `DOCKER-USER`. Semak semula selepas setiap upgrade Docker (runbook §6.3).
