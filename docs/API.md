# Rujukan API — StaffBot.my

> Dikemas kini 19 Okt 2026 berdasarkan `api/app/routers/`. Base URL: `https://staffbot.my`.

**Legenda auth**

| Kod | Maksud |
| :--- | :--- |
| **P** | Awam, tiada auth |
| **C** | JWT pelanggan (`Authorization: Bearer`) |
| **A** | JWT admin (email = `STAFFBOT_ADMIN_EMAIL`) |
| **C/I** | JWT pelanggan, atau `X-Internal-Key` + `X-Client-ID` |
| **I** | `x-api-key` = `STAFFBOT_SERVER_B_API_KEY` |
| **S** | Tandatangan Stripe |

⚠️ menandakan isu keselamatan. Lihat `SECURITY_FINDINGS.md`.

## Auth — `/api/v1/auth`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| POST | /register | P | Daftar (status `pending`, rizab subdomain, cipta subscription) |
| POST | /login | P | Body JSON `{email,password}` → `{access_token}` (JWT 24 jam) |
| POST | /change-password | C | Tukar password |
| GET | /me | C | Profil semasa |
| GET | /office-token | C | Token untuk Agent Office |

## Pelanggan — `/api/v1/clients`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET | / | A | Senarai semua klien |
| GET | /{id} | C (diri sendiri) / admin | Butiran klien |
| PUT | /{id} | C | Kemas kini profil. ⚠️ Pelanggan boleh menukar `package`, `status` dan `email` sendiri |
| POST | /setup | C | Onboarding: BYOK, token Telegram, nombor WhatsApp |
| GET | /{id}/api-keys | C | Senarai API key |
| POST | /{id}/platform/whatsapp | C | Mulakan sesi WhatsApp |
| POST | /{id}/platform/telegram | C | Daftar bot Telegram |
| POST | /{id}/deploy | A | Force deploy container |
| GET/POST | /me/search-config/ | C | Konfigurasi carian web |
| DELETE | /me/search-config/{id} | C | Padam konfigurasi carian web |
| GET/POST | /me/email-config/ | C | Konfigurasi SMTP |
| DELETE | /me/email-config/{id} | C | Padam konfigurasi SMTP |

## Bot ("AI Staff") — `/api/v1/containers`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET/POST | / | C | Senarai / cipta bot (had `bot_limit` pakej) |
| GET/PUT/DELETE | /{id} | C | Baca / kemas kini / padam. ⚠️ Padam akan membuang container yang dikongsi oleh semua bot klien |

## Chat — `/api/v1/chat`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| POST | /send | C | Hantar mesej. Body: `{content, container_id, provider?, model?, api_key?, image_base64?}` |
| GET | /history | C | Sejarah chat |
| GET | /token-status | C | Status kuota |
| POST | /upload | C/I | Ekstrak teks fail (≤10 MB) |
| POST | /extract-link | C/I | Ambil kandungan URL. ⚠️ Tiada perlindungan SSRF |

## Tugasan — `/api/v1/tasks`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET | /list | C/I | Senarai tugasan |
| POST | /create | C/I | Cipta tugasan |
| GET/PUT/DELETE | /{id} | C/I | Baca / kemas kini / padam tugasan |
| GET | /stats/summary | C/I | Ringkasan statistik tugasan |

## Memori — `/api/v1/memory`
⚠️ Kebanyakan endpoint di sini mengimport modul yang tiada dalam repo (`memory_service`, `memory_processor`) **[SAHKAN-SERVER]**.

| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| POST | /add | C | Tambah item memori |
| POST | /upload | C | Upload dokumen, pecah kepada chunks |
| POST | /extract-link | C | Ambil URL ke memori |
| GET | /search | C | Carian |
| GET | /recent | C | Item terkini |
| GET | /stats | C | Statistik |
| GET | /audit-log | C | Log audit memori |
| GET/PUT/DELETE | /{id} | C | Baca / kemas kini / padam item |
| DELETE | /type/{type} | C | Padam ikut jenis |
| DELETE | /clear/all | C | Padam semua |
| POST | /backfill-embeddings | C | Jana embedding untuk baris yang belum ada |
| POST | /admin/retention-cleanup | A | Pembersihan ikut tempoh simpanan |
| POST | /admin/delete-customer/{id} | A | Padam memori seorang pelanggan |

## Billing dan langganan
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET | /api/v1/billing/topup-packages | P | Pakej top-up |
| POST | /api/v1/billing/topup-checkout?package_id= | C | Stripe checkout untuk top-up |
| GET | /api/v1/billing/topup-history | C | Sejarah top-up |
| GET | /api/v1/billing/usage | C | Kuota dan penggunaan |
| POST | /api/v1/subscriptions/create-checkout?package= | C | Stripe checkout untuk pakej |
| GET | /api/v1/subscriptions/{client_id} | C | Langganan |
| PUT | /api/v1/subscriptions/{client_id}/tokens | ⚠️ **P (tiada auth)** | Tetapkan token yang telah digunakan |
| GET | /api/v1/packages/public | P | Pakej untuk laman utama |

## Penyedia LLM (pelanggan) — `/api/v1/providers`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET | /available | C | Penyedia dalam pakej |
| GET | /usage | C | Penggunaan per penyedia |
| GET | /daily-usage | C | Penggunaan harian |
| GET | /byok-status | C | Status BYOK |
| POST | /toggle-byok | C | Simpan atau toggle kunci BYOK |

## Notifikasi — `/api/v1/notifications`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET/POST | /channels | C | Senarai / tambah saluran |
| PUT/DELETE | /channels/{id} | C | Kemas kini / buang saluran |
| GET | /log | C | Sejarah notifikasi |
| POST | /test | C | Hantar notifikasi ujian |

## Affiliate — `/api/v1/affiliates`
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| GET | /dashboard | C | Ringkasan |
| GET | /profile | C | Profil |
| GET | /referrals | C | Rujukan |
| GET | /commissions | C | Komisen |
| POST | /register | C | Daftar sebagai affiliate |
| POST/GET | /payouts | C | Minta / senarai bayaran |
| POST | /copywriting | C | Teks pemasaran (templat statik) |
| GET | /leaderboard | P | Papan pendahulu |
| POST | /track-click | P | Rekod klik |
| POST | /convert | ⚠️ P | Kaitkan klien dengan affiliate |

## Webhook masuk
| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| POST | /api/v1/webhooks/stripe | S | `checkout.session.completed` (pakej atau top-up) |
| POST | /api/v1/webhooks/server-b/status | `X-API-Key` | Status container. ⚠️ Lulus jika kunci kosong |
| GET/POST | /api/v1/webhooks/config/ | C | Konfigurasi webhook keluar (untuk tool `call_webhook`) |
| GET/PUT/DELETE | /api/v1/webhooks/config/{id} | C | Baca / kemas kini / padam satu konfigurasi |

## Admin — `/api/v1/admin` (semua A, kecuali yang dinyatakan)
| Kumpulan | Endpoint |
| :--- | :--- |
| Dashboard | `GET /dashboard`, `/dashboard/token-usage`, `/health`, `/usage/tokens`, `/activity`, `/billing/overview`, `/revenue`, `/usage/by-client` |
| Pengguna (klien) | `GET/POST /users`, `GET/PUT/DELETE /users/{id}`, `POST /users/{id}/deploy`, `GET /users/{id}/token-usage`, `GET /users/container-stats`, `GET /users/containers/list` |
| Pakej | `GET /packages` (⚠️ P), `GET /packages/all`, `GET /packages/categories`, `POST /packages`, `PUT/DELETE /packages/{id}`, `POST /packages/{id}/apply` (tiada kesan) |
| Penyedia LLM | `GET/POST /providers/providers`, `GET/PUT/DELETE /providers/providers/{id}`, `POST /providers/providers/{id}/test`, `GET /providers/providers/active` (P), `GET/POST /providers/package-providers`, `PUT/DELETE /providers/package-providers/{id}` |
| Subdomain | `GET/POST /subdomains`, `GET /subdomains/available`, `PUT/DELETE /subdomains/{id}` |
| Tetapan | `GET/PUT /settings` (⚠️ GET memulangkan kunci Stripe dalam bentuk nyahsulit) |
| Bayaran | `GET /payments/status`, `GET /payments/transactions` |
| Top-up | `GET/POST /topup-packages`, `PUT/DELETE /topup-packages/{id}`, `GET /topup-packages/history` |
| Polisi | `GET/PUT /policy/skills`, `GET/PUT /policy/tools`, `GET/PUT /policy/policy` |
| Affiliate | `GET /affiliates`, `/affiliates/leaderboard`, `/affiliates/{id}`, `PUT /affiliates/{id}`, `/affiliates/{id}/referrals`, `/affiliates/{id}/commissions`, `/affiliates/payouts/all`, `PUT /affiliates/payouts/{id}`, `/affiliates/stats/summary` |

## Dalaman (gateway → API) — `/api/v1/internal` (semua I)
| Method | Path | Fungsi |
| :--- | :--- | :--- |
| POST | /provider/resolve | Konfigurasi penyedia **dengan kunci nyahsulit** |
| GET | /provider/list | Senarai penyedia aktif |
| POST | /client/{id}/telegram/setup | Arahan `/connect` dari Telegram |
| POST | /client/{id}/tasks/create | Cipta tugasan dari pengelas |
| POST | /webhook/resolve | Konfigurasi webhook dengan nilai auth nyahsulit |
| POST | /search-config/resolve | Konfigurasi carian dengan kunci nyahsulit |
| POST | /email-config/resolve | Konfigurasi SMTP dengan password nyahsulit |
| POST | /email-config/upsert | Simpan konfigurasi SMTP |
| POST | /audit/log | Tulis audit |

## Gateway (`staffbot-gateway:8080`, dalaman sahaja)
Auth: `x-api-key` atau `Authorization: Bearer` = `AUTH_KEY` gateway. **Jangan tulis nilai kunci dalam dokumen.**

| Method | Path | Fungsi |
| :--- | :--- | :--- |
| GET | /health | Semak kesihatan |
| POST | /v1/chat/completions | Proksi LLM serasi OpenAI + ReAct + tool (laluan utama) |
| POST | /api/chat/send | Chat lama (digunakan oleh container klien) |
| GET | /api/chat/history | Sejarah chat |
| POST | /api/memory/search | Carian Central Brain v2. Body `{client_id, query, limit}` |
| POST | /api/memory/save | Simpan memori. Body `{client_id, content, metadata}` |
| POST | /api/memory/classify-and-save | Klasifikasi pertukaran dan simpan |
| POST | /api/deploy | Deploy container |
| POST | /api/container/{name}/action | start/stop/restart/delete. ⚠️ Nama tidak disahkan |
| GET | /api/container/{name}/status | Status container |
| GET | /api/containers | Senarai container |
| POST | /api/container/{name}/update-resources | Kemas kini had CPU/RAM |
| POST | /api/notify/whatsapp[/{cid}] | Hantar notifikasi WhatsApp |
| POST | /api/notify/telegram/{cid} | Hantar notifikasi Telegram |
| POST | /api/incoming/whatsapp/{cid} | Mesej masuk WhatsApp (`x-gateway-key`) |
| POST | /api/incoming/telegram/{cid} | Mesej masuk Telegram (`x-gateway-key`) |

## Managed Hermes (baharu, 23 Okt 2026)

| Method | Path | Auth | Fungsi |
| :--- | :--- | :--- | :--- |
| POST | /api/v1/channels/incoming/{whatsapp\|telegram}/{client_id} | `x-gateway-key` (pengurus) | Mesej masuk. Pelanggan tanpa Hermes dihantar ke gateway lama |
| POST | /api/v1/channels/web/chat | C | Chat web dengan Hermes pelanggan (SSE). Body `{message, conversation}` |
| GET | /api/v1/agent/me | C | Status Hermes + ciri pakej |
| POST | /api/v1/agent/wake | C | Hidupkan container |
| POST | /api/v1/agent/console-ticket | C | Tiket console sekali guna (60 s) |
| WS | /api/v1/agent/console?ticket=TIKET | tiket | Web Console (mesej JSON `input`/`resize`; output binari). Kod tutup 4403 jika tidak dibenarkan. JWT login tidak diterima di sini, dan tiket tidak diterima sebagai token API |
| GET | /api/v1/admin/hermes/instances | A | Semua container pelanggan |
| POST | /api/v1/admin/hermes/{client_id}/{provision\|wake\|sleep\|backup\|apply-package\|deprovision} | A | Tindakan per pelanggan |
| POST | /api/v1/admin/hermes/rollout | A | Upgrade image: `{image, client_ids?, percent?, batch_size}` |
| POST | /api/v1/admin/packages/{id}/apply | A | Guna tetapan pakej pada semua container pelanggannya |

**Agent tools** (dipanggil oleh plugin StaffBot dalam container; auth `Bearer sbk_...` token pelanggan; dilayan oleh API dan LLM proxy):

| Method | Path | Fungsi |
| :--- | :--- | :--- |
| POST/GET | /api/v1/agent-tools/tasks | Cipta / senarai tugasan |
| PATCH | /api/v1/agent-tools/tasks/{id} | Kemas kini tugasan |
| GET | /api/v1/agent-tools/webhooks | Senarai API perniagaan yang disambung (tanpa rahsia) |
| POST | /api/v1/agent-tools/webhook | Panggil API pelanggan (SSRF dikawal, 10/min) |
| POST | /api/v1/agent-tools/email | Hantar email melalui SMTP pelanggan (50/hari) |

**LLM proxy** (`staffbot-llm-proxy:8090`, untuk container pelanggan sahaja): `POST /v1/chat/completions` (stream dan bukan stream), `GET /v1/models`, `GET /health`. Auth: `Bearer sbk_<id>_<versi>_<hmac>`.

## Halaman web
- Pelanggan (`/customer/*.html`): login, dashboard, bots, chat, tasks, billing, usage, settings, affiliates, providers, office.
- Admin (`/admin/*.html`): login, dashboard, users, user-detail, subdomains, packages, billing, usage, payments, providers, token-topups, policy, settings, affiliates (6 halaman), chat, my-staff-ai.

JWT disimpan dalam `localStorage['staffbot_token']`.
