# PROJECT BRIEF — Enterprise Hermes Hub (Voice & Mobile AI Assistant)

> **Untuk:** Claude Code
> **Pemilik projek:** Remy (Norzureimy Bin Mursal), Marz Technology & Trading
> **Tarikh:** 19 Oktober 2026
> **Status:** Pra-pembangunan. Fasa 0 (Discovery) belum bermula.
> **Nama produk:** "Enterprise Hermes Hub" ialah nama kerja sahaja dan belum muktamad.

Dokumen ini ada empat bahagian:

1. **Laporan Projek.** Apa yang sudah diketahui, apa yang telah diputuskan, dan apa yang masih terbuka.
2. **Jalan Cerita.** Masalah, visi produk dan perjalanan pengguna.
3. **PRD v2.** Keperluan produk yang telah dipinda daripada PRD asal.
4. **Arahan untuk Claude Code.** Apa yang perlu dibuat, mengikut urutan, dan peraturan yang mesti dipatuhi.

> ⚠️ **Baca Bahagian 4 dahulu sebelum menyentuh mana-mana server.** Fasa 0 dijalankan dalam mod BACA SAHAJA.

---

# BAHAGIAN 1 — LAPORAN PROJEK

## 1.1 Ringkasan

Remy mahu membina platform asisten AI perusahaan yang boleh digunakan melalui **web** dan **mobile app (iOS/Android)**. Staf boleh berinteraksi dengan ejen AI melalui **teks** atau **suara**, termasuk mod bebas tangan dengan wake word seperti "Hey Hermes". Ejen AI menjawab dan melaksanakan tugas mengikut **SOP syarikat**, dengan akses kepada data perniagaan melalui **MCP (Model Context Protocol)**.

Remy sudah memiliki produk **StaffBot.my** (juga keluaran Marz Technology & Trading). StaffBot ialah platform "AI Employee" berbilang klien yang kelihatan merangkumi sebahagian besar keperluan backend projek ini. **Projek ini sepatutnya dibina sebagai lanjutan StaffBot**, iaitu lapisan suara, mobile dan struktur perusahaan, dan bukan sistem baharu dari kosong. Cadangan ini perlu disahkan melalui Fasa 0.

## 1.2 Apa yang diketahui tentang StaffBot.my (dari laman awam sahaja)

Sumber: https://staffbot.my (dibaca 19 Okt 2026). Semua butiran dalaman **BELUM DISAHKAN** dan perlu disemak dalam Fasa 0.

| Perkara | Apa yang dinyatakan di laman awam |
| :--- | :--- |
| Konsep | "AI Employee / Digital Employee as a Service" untuk perniagaan Malaysia |
| Multi-tenancy | Setiap klien ada subdomain sendiri (`namasyarikat.staffbot.my`) |
| Pengasingan data | Setiap klien mendapat **container Docker yang berasingan** |
| API key | Menyokong **BYOK (Bring Your Own Key)**. Bila guna kunci sendiri, kuota token terurus tidak terpakai |
| Saluran | WhatsApp, Telegram, Dashboard web |
| Keupayaan ejen | Belajar SOP, profil syarikat dan produk; memori kekal; automasi aliran kerja |
| Integrasi | Google Drive, Email, Stripe, CRM, API, Google Sheets, web crawl, Zapier |
| Login pelanggan | `https://staffbot.my/customer/login.html` |
| Pendaftaran | Nama, email, nama syarikat, subdomain, telefon (WhatsApp), pelan, password |
| Harga | Pelan bermula RM49/bulan, percubaan percuma 7 hari |
| Pemilik | Marz Technology & Trading |

**Lokasi server StaffBot belum diketahui.** Remy tidak ingat VPS mana yang meng-host StaffBot. Remy mengurus server melalui aaPanel, ServerAvatar, cPanel dan Docker, dengan penyedia Contabo, GreenCloud VPS, OVH dan Azure.

**Apa yang StaffBot BELUM ada** (berdasarkan laman awam):

- Mobile app (iOS/Android)
- Input dan output suara (wake word, STT, TTS)
- Struktur cawangan dan jabatan dengan RBAC
- Aliran kelulusan (approval) untuk tindakan sensitif

## 1.3 Keputusan yang telah dibuat oleh Remy

| # | Keputusan | Sumber |
| :--- | :--- | :--- |
| K1 | Bina **mobile app dan web** | Remy |
| K2 | API ejen AI **tidak dikongsi**. **Setiap syarikat ada API sendiri** | Remy |
| K3 | **Setiap staf (user) juga ada API ejen sendiri** | Remy |
| K4 | Login menghubungkan app/web kepada API ejen AI pengguna tersebut | Remy |
| K5 | Mobile app guna satu login sahaja; backend yang tentukan tenant pengguna | Remy |

## 1.4 Cadangan seni bina (dipersetujui secara prinsip, perlu disahkan dengan kod sebenar)

| # | Cadangan |
| :--- | :--- |
| C1 | Jadual `tenants` duduk dalam **database backend sahaja**. Web dan mobile hanya klien yang memanggil API login yang sama. |
| C2 | Selepas login, backend pulangkan **JWT yang mengandungi `user_id` + `tenant_id`**. Semua request seterusnya bawa token ini. |
| C3 | **Kunci API ejen TIDAK PERNAH disimpan atau dihantar ke app/web.** Backend panggil ejen bagi pihak pengguna. |
| C4 | Kunci API disimpan **disulitkan** (AES-256-GCM, kunci induk dari env/secret manager). |
| C5 | Urutan resolusi API: **kunci staf → kunci default syarikat → (pilihan) kunci terurus StaffBot**. |
| C6 | Email yang sama mungkin wujud di dua syarikat. Login perlu **kod syarikat** atau **subdomain** untuk mengenal pasti tenant. StaffBot sudah guna subdomain. |
| C7 | Jika StaffBot memang guna model "satu container untuk satu klien", jadual `tenants` mungkin hanya perlu di **portal pusat** (signup, billing, routing ke container). Dalam setiap container, tenant adalah tetap. **Tentukan selepas Fasa 0.** |
| C8 | Bina projek ini sebagai **lanjutan StaffBot**: mobile app baharu + modul suara + modul enterprise (cawangan, jabatan, RBAC, approval) di atas backend sedia ada. |
| C9 | Mobile: **Flutter** (Remy biasa guna). Lapisan AI dan suara: ikut stack StaffBot sedia ada jika sesuai, atau servis **FastAPI** berasingan. Tentukan selepas Fasa 0. |

## 1.5 Jurang (gaps) dalam PRD asal yang telah dikenal pasti

**Kritikal**

1. Tiada jadual `tenants`, dan tiada `tenant_id` pada jadual utama.
2. Tiada senarai fungsi, user story atau acceptance criteria mengikut peranan.
3. Tiada pembahagian MVP atau fasa. Skop terlalu luas untuk versi pertama.
4. Tiada human-in-the-loop untuk tindakan sensitif (refund, pesanan, kemas kini stok). `allowed_tools` hanya ditetapkan per ejen, bukan per peranan.

**Realiti teknikal**

5. **iOS tidak membenarkan mikrofon sentiasa mendengar di background.** Android perlu foreground service dengan notifikasi kekal. Mod hands-free hanya realistik semasa app dibuka. Di browser, tab mesti aktif dan kebenaran mic mesti diberi.
6. **Porcupine (Picovoice) perlu lesen komersial.** Kos perlu dimasukkan dalam harga jualan. Alternatif: openWakeWord (open source), tetapi integrasi mobile lebih sukar.
7. Ketepatan Whisper untuk Bahasa Melayu dan Manglish **perlu diuji** dengan rakaman sebenar. Pilihan suara TTS Bahasa Melayu (Piper, ElevenLabs) adalah terhad, jadi perlu diuji.
8. `sop_documents` menyimpan **satu embedding untuk satu dokumen**, dan ini tidak sesuai untuk RAG. Perlu jadual `sop_chunks`.
9. Dimensi embedding (`vector(1536)`) terikat pada model tertentu. Simpan nama model embedding bersama vektor.

**Jadual yang tiada:** `tenants`, `tenant_agent_config`, `user_agent_credentials`, `sop_chunks`, `role_tool_permissions`, `approvals`, `device_tokens`, `refresh_tokens`, `usage_logs`.

**Bukan teknikal**

10. Tiada sasaran prestasi (latency, pengguna serentak, uptime).
11. Tiada anggaran kos LLM, STT dan TTS per staf sebulan. Ini diperlukan untuk menetapkan harga.
12. Tiada pematuhan **PDPA 2010**: persetujuan rakaman suara, tempoh simpanan audio, hak padam data.
13. Tiada skrin admin (setup tenant, urus staf, upload SOP, konfigurasi ejen, laporan).
14. Harga pakej di Seksyen 8 masih kosong.
15. Banyak pilihan "A atau B" dalam tech stack belum dimuktamadkan.

## 1.6 Soalan terbuka untuk Remy

| # | Soalan | Kenapa penting |
| :--- | :--- | :--- |
| S1 | Server mana yang meng-host StaffBot? | Fasa 0 bergantung pada ini |
| S2 | Adakah projek ini untuk **semua klien StaffBot** (ciri tambahan) atau **produk berasingan** untuk klien enterprise? | Menentukan sama ada perlu ubah StaffBot atau bina di sebelahnya |
| S3 | Siapa yang cipta dan masukkan API key staf: admin syarikat, staf sendiri, atau automatik? | Reka bentuk skrin admin dan aliran onboarding |
| S4 | "API ejen" setiap staf itu API penyedia LLM (OpenAI/Claude/dll.) atau endpoint ejen Hermes yang berasingan? | Reka bentuk jadual credentials dan lapisan penghala |
| S5 | iOS diperlukan dalam MVP, atau Android dahulu? | Kos dan masa (akaun Apple Developer, semakan App Store) |
| S6 | STT/TTS: cloud API (cepat dibina, kos per penggunaan) atau self-host (kos server, kawalan data)? | Kos dan pematuhan |
| S7 | Harga pakej setup dan bulanan? | Model bisnes |
| S8 | Klien pertama atau pilot yang akan menguji? | Fokus MVP |
| S9 | ERP yang perlu disambung dahulu? (Remy sendiri guna ERPNext di erp.marz.biz.my, yang mungkin sesuai sebagai integrasi MCP pertama) | Skop Fasa 3 |

---

# BAHAGIAN 2 — JALAN CERITA

## 2.1 Masalah

Banyak syarikat kecil dan sederhana di Malaysia ada beberapa cawangan dan jabatan, tetapi **tiada jabatan IT**. Staf cawangan sering perlu:

- menyemak stok, kehadiran, status pesanan atau prosedur;
- bertanya kepada ibu pejabat atau mencari dalam fail SOP yang berselerak;
- mengisi borang atau sistem semasa tangan sibuk (di stor, kaunter, lapangan).

Chatbot biasa tidak kenal SOP syarikat, tidak boleh bertindak, dan tidak sesuai untuk staf yang tangannya sibuk.

## 2.2 Visi

> "Setiap staf ada pembantu AI yang kenal SOP syarikat, boleh dicapai dengan suara atau teks, di web atau telefon, dan boleh melaksanakan kerja, bukan sekadar menjawab."

Marz sudah membina **StaffBot.my**: ejen AI yang belajar SOP, ada memori, dan boleh diakses melalui WhatsApp, Telegram dan dashboard. Langkah seterusnya ialah membawa ejen yang sama ke **mobile app dan web enterprise**, dengan:

- **suara** (tekan untuk bercakap, kemudian wake word "Hey Hermes");
- **struktur perusahaan**: cawangan, jabatan, peranan;
- **kawalan**: kelulusan untuk tindakan sensitif, dan log audit penuh.

## 2.3 Watak (personas)

| Persona | Peranan | Keperluan utama |
| :--- | :--- | :--- |
| **Remy / Marz** | Super Admin (penyedia platform) | Onboard klien, pantau server, urus pelan dan billing |
| **Puan Aini** | Admin Syarikat (klien) | Daftar cawangan, jabatan dan staf; masukkan API; upload SOP; lihat laporan |
| **Encik Faris** | Pengurus Cawangan Klang | Lihat aktiviti cawangan, luluskan permintaan staf |
| **Amir** | Staf Operasi / Stor | Bertanya dan bertindak dengan suara semasa tangan sibuk |
| **Siti** | Staf Pejabat (HR) | Guna web untuk soalan SOP dan laporan kehadiran |

## 2.4 Perjalanan pengguna (user journeys)

### J1 — Onboarding syarikat baharu (Super Admin + Admin Syarikat)

1. Remy cipta tenant baharu di portal pusat (atau klien daftar sendiri melalui StaffBot): nama syarikat, subdomain dan pelan.
2. Puan Aini log masuk ke `syarikat.<domain>`, kemudian daftar cawangan (Klang, Subang) dan jabatan (Operasi, HR, Kewangan).
3. Puan Aini masukkan **API default syarikat** di skrin Tetapan Ejen. Kunci disulitkan sebaik sahaja disimpan dan tidak dipaparkan semula (hanya 4 aksara terakhir).
4. Puan Aini jemput staf melalui email atau WhatsApp. Setiap staf ditetapkan kepada cawangan, jabatan dan peranan.
5. Jika perlu, Puan Aini masukkan **API khusus untuk staf tertentu**.
6. Puan Aini upload SOP mengikut jabatan. Sistem memecahkan dokumen kepada chunks dan menjana embedding.

### J2 — Staf log masuk di mobile

1. Amir buka app dan masukkan **kod syarikat** (atau pilih syarikat), email dan password.
2. Backend sahkan, kemudian pulangkan JWT (`user_id`, `tenant_id`, `branch_id`, `role`) dan refresh token.
3. App daftar `device_token` untuk push notification.
4. App **tidak pernah** menerima API key ejen.

### J3 — Pertanyaan suara (Fasa 1: tekan untuk bercakap)

1. Amir tekan dan tahan butang mic, kemudian berkata: "Semak baki kotak saiz L di stor hari ini."
2. Audio dihantar ke `POST /voice/transcribe`, dan Whisper menukarnya kepada teks.
3. Backend tentukan API ejen (kunci Amir → kunci syarikat), kemudian hantar mesej bersama konteks (cawangan Klang, jabatan Operasi, SOP berkaitan).
4. Ejen panggil tool `query_branch_inventory` melalui MCP dan mendapat 42 unit.
5. Ejen jawab: "Baki 42 unit, di bawah paras minimum SOP (50). Nak saya sediakan draf pesanan?"
6. App papar teks. Dalam Fasa 2, app turut memainkan suara (TTS).

### J4 — Tindakan sensitif dengan kelulusan

1. Amir: "Ya, buat draf pesanan 100 unit."
2. Ejen cipta rekod `approvals` (status `PENDING`), dan TIDAK melaksanakan pesanan terus.
3. Encik Faris menerima push notification, lalu menyemak dan menekan **Lulus**.
4. Sistem laksanakan tindakan, rekod dalam `audit_logs`, dan maklumkan Amir.

### J5 — Mod bebas tangan (Fasa 2)

1. Amir buka app dalam mod "Hands-free". Indikator hijau menunjukkan app sedang mendengar wake word secara lokal.
2. Tiada audio dihantar ke server sehingga "Hey Hermes" dikesan di peranti.
3. Selepas wake word dikesan, indikator bertukar merah dan audio distream melalui WebSocket. Respons teks dan suara kembali secara streaming.
4. Jika app ditutup atau skrin dikunci, mod hands-free berhenti (had iOS). Pengguna dimaklumkan dengan jelas.

### J6 — Laporan dan audit (Admin)

Puan Aini membuka dashboard web untuk melihat:

- penggunaan per staf dan cawangan (bilangan mesej, minit audio, token);
- log audit tindakan;
- permintaan kelulusan yang tertunggak.

---

# BAHAGIAN 3 — PRD v2 (DIPINDA)

> Berdasarkan PRD asal Remy ("Enterprise AI Voice & Workflow Automation System"), dengan pindaan dari Bahagian 1.5.
> Semua yang bertanda **[SAHKAN-F0]** mesti disemak semula selepas Fasa 0 berdasarkan kod StaffBot sebenar.

## 3.1 Matlamat produk

Platform automasi operasi perusahaan yang dipacu ejen AI (Hermes Agent / LLM), dengan input dwi-mod (**teks** dan **suara**), boleh dicapai melalui **web** dan **mobile**. Platform ini mematuhi SOP setiap syarikat, dengan data dan orkestrasi diurus secara berpusat di Cloud/VPS.

## 3.2 Skop platform

| Komponen | Pengguna | Fungsi utama |
| :--- | :--- | :--- |
| **Web App** | Admin syarikat, pengurus, staf pejabat | Chat teks + suara (push-to-talk), panel admin, laporan, kelulusan |
| **Mobile App** (Android dahulu, kemudian iOS) | Staf operasi dan lapangan, pengurus | Chat suara + teks, hands-free (foreground sahaja), notifikasi, kelulusan |
| **Backend** | Semua | Auth, tenant, penghala API ejen, STT/TTS, RAG, MCP, audit **[SAHKAN-F0: lanjutkan backend StaffBot atau servis berasingan]** |
| **Portal Pusat** | Super Admin (Marz) | Onboard tenant, pelan, billing, pemantauan |

## 3.3 Peranan dan kebenaran (RBAC)

| Peranan | Skop data | Boleh |
| :--- | :--- | :--- |
| `SUPER_ADMIN` | Semua tenant | Cipta, gantung dan padam tenant; lihat penggunaan semua klien |
| `TENANT_ADMIN` | Seluruh syarikat | Urus cawangan, jabatan, staf, API ejen, SOP, ejen; lihat semua log |
| `MANAGER` | Cawangan sendiri | Lihat aktiviti cawangan, luluskan permintaan, guna ejen |
| `STAFF` | Diri sendiri + cawangan sendiri | Guna ejen (teks/suara), lihat sejarah sendiri, hantar permintaan |

Peraturan wajib:

- Staf cawangan A **tidak boleh** mendapatkan data cawangan B melalui ejen, kecuali `TENANT_ADMIN`.
- Tapisan ini dikuatkuasakan di backend dan tool MCP, **bukan bergantung pada prompt**.
- Tool yang bertanda `requires_approval = true` hanya boleh dicipta sebagai `approvals`, dan dilaksanakan selepas diluluskan oleh `MANAGER` atau `TENANT_ADMIN`.

## 3.4 Keperluan fungsian (mengikut fasa)

### Fasa 1 — MVP (teks + push-to-talk)

| ID | Keperluan | Acceptance criteria |
| :--- | :--- | :--- |
| F1.1 | Login web dan mobile (kod syarikat/subdomain + email + password) | JWT mengandungi `user_id`, `tenant_id`, `branch_id`, `role`. Access token 15 minit, refresh token 30 hari, boleh dibatalkan |
| F1.2 | Pengurusan tenant (portal pusat) | Super Admin boleh cipta tenant dan subdomain, dan gantung tenant |
| F1.3 | Pengurusan cawangan, jabatan dan staf | Tenant Admin boleh CRUD; jemputan staf melalui email |
| F1.4 | Konfigurasi API ejen syarikat | Kunci disimpan disulitkan; hanya 4 aksara akhir dipaparkan; butang "Uji sambungan" |
| F1.5 | Konfigurasi API ejen per staf | Kunci per staf, jika tiada guna default syarikat; resolusi dilakukan di backend sahaja |
| F1.6 | Chat teks dengan ejen | Respons streaming; sejarah sesi disimpan; konteks cawangan dan jabatan dihantar |
| F1.7 | Push-to-talk (web + mobile) | Rakam, hantar, dapat transkrip dalam < 3 s untuk audio 10 s; transkrip boleh disunting sebelum dihantar |
| F1.8 | Upload SOP + RAG | PDF/DOCX/TXT dipecah kepada chunks dengan embedding; ejen memetik SOP yang digunakan |
| F1.9 | Log audit | Login, perubahan konfigurasi dan setiap tool call direkodkan |
| F1.10 | Rekod penggunaan | Mesej, token, minit audio direkod per user dan tenant |

### Fasa 2 — Suara penuh

| ID | Keperluan | Acceptance criteria |
| :--- | :--- | :--- |
| F2.1 | TTS untuk respons ejen | Suara dimainkan dalam app; boleh dimatikan; sokong BM dan EN |
| F2.2 | Streaming suara melalui WebSocket | `WSS /ws/v1/voice-stream`, PCM 16 kHz; respons pertama < 1.5 s selepas pengguna berhenti bercakap (sasaran) |
| F2.3 | Wake word "Hey Hermes" (foreground) | Pengesanan di peranti; tiada audio keluar sebelum wake word; indikator visual hijau/merah |
| F2.4 | Android foreground service (pilihan) | Notifikasi kekal semasa mendengar; boleh dimatikan oleh pengguna |
| F2.5 | Push notification | Untuk kelulusan, jawapan ejen yang tertunda, pengumuman admin |

### Fasa 3 — Enterprise

| ID | Keperluan | Acceptance criteria |
| :--- | :--- | :--- |
| F3.1 | Aliran kelulusan | Tool sensitif mencipta `approvals`; pengurus lulus atau tolak di web/mobile; tindakan dilaksanakan selepas lulus |
| F3.2 | Kebenaran tool per peranan | Jadual `role_tool_permissions` dikuatkuasakan di backend |
| F3.3 | Ejen per jabatan | Prompt, model dan tool berbeza per jabatan |
| F3.4 | Integrasi MCP: ERP | Sambungan pertama, contohnya ERPNext (Remy guna ERPNext di erp.marz.biz.my) |
| F3.5 | Dashboard laporan | Penggunaan, kos dan aktiviti per cawangan; eksport CSV |
| F3.6 | Speaker verification (pilihan) | `voice_profile_id` untuk pengesahan suara bagi tindakan sensitif |

## 3.5 Tech stack (cadangan, muktamadkan selepas Fasa 0)

| Komponen | Pilihan | Nota |
| :--- | :--- | :--- |
| Mobile | **Flutter** | Remy biasa guna; satu kod untuk Android + iOS |
| Web frontend | Ikut StaffBot sedia ada **[SAHKAN-F0]**; jika baharu: React + Tailwind (Remy biasa guna) | Web Audio API untuk rakaman |
| Backend utama | Lanjutkan backend StaffBot **[SAHKAN-F0]** | Elakkan dua sistem auth yang berasingan |
| Servis AI/Suara | FastAPI (Python), jika StaffBot tidak sesuai untuk WebSocket audio | STT, TTS, penghala ejen, RAG |
| Wake word | Porcupine (lesen komersial) **atau** openWakeWord | Uji kedua-dua; masukkan kos lesen dalam harga |
| STT | Whisper (API dahulu; self-host whisper.cpp/faster-whisper kemudian) | Uji dengan rakaman BM dan Manglish sebenar |
| TTS | Uji ElevenLabs vs Piper vs penyedia lain untuk BM | Pilih berdasarkan kualiti suara BM |
| Ejen | Hermes Agent / ejen StaffBot sedia ada **[SAHKAN-F0]** | Melalui API per tenant/per staf |
| Tools | MCP servers | Inventori, SOP, ERP |
| DB | PostgreSQL + pgvector | Ikut DB StaffBot jika berbeza **[SAHKAN-F0]** |
| Cache/Queue | Redis | Sesi, rate limit, job embedding |
| Infra | Docker, Nginx, Ubuntu VPS, TLS 1.3 | Ikut corak deployment StaffBot |

## 3.6 Seni bina sistem (v2)

```
[Mobile App (Flutter)]        [Web App]
   │  push-to-talk / wake word (lokal)
   │  JWT sahaja — TIADA API key ejen di klien
   ▼
[Nginx  (TLS 1.3, subdomain → tenant)]
   ▼
[Backend API]  ── Auth (JWT: user_id, tenant_id, branch_id, role)
   │           ── RBAC + tapisan cawangan
   │           ── Tenant / Branch / Dept / User admin
   │
   ├── [Servis Suara]  STT (Whisper)  →  teks
   │                   TTS            ←  teks
   │
   ├── [Penghala Ejen]
   │      1. Ambil kunci: user_agent_credentials → tenant_agent_config → (managed)
   │      2. Nyahsulit kunci dalam memori sahaja
   │      3. Tambah konteks: cawangan, jabatan, SOP (RAG)
   │      4. Panggil API ejen (Hermes / StaffBot agent / LLM)
   │               │
   │               └── MCP Client → [Inventori] [SOP] [ERP]
   │                     (setiap tool semak role_tool_permissions;
   │                      tool sensitif → approvals)
   │
   └── [Audit + Usage]  audit_logs, usage_logs
   ▼
[PostgreSQL + pgvector]   [Redis]
```

## 3.7 Skema pangkalan data (v2)

> **[SAHKAN-F0]** Jika StaffBot sudah ada jadual setara (users, companies, dsb.), **guna dan lanjutkan jadual sedia ada**. Jangan cipta jadual pendua. Skema di bawah ialah sasaran logik.
> Jika model "satu container untuk satu tenant" disahkan, `tenant_id` dalam container boleh dikekalkan sebagai lapisan keselamatan tambahan, atau dibuang. Keputusan ini perlu dibuat bersama Remy.

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "vector";

-- 0. Tenant (syarikat klien)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_code VARCHAR(30) UNIQUE NOT NULL,      -- digunakan semasa login mobile
    subdomain VARCHAR(63) UNIQUE NOT NULL,        -- cth: syarikat → syarikat.<domain>
    company_name VARCHAR(150) NOT NULL,
    plan_code VARCHAR(30) NOT NULL DEFAULT 'TRIAL',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, SUSPENDED, CANCELLED
    data_retention_days INT NOT NULL DEFAULT 90,  -- PDPA: tempoh simpanan audio/mesej
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 1. Cawangan
CREATE TABLE branches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_code VARCHAR(20) NOT NULL,
    branch_name VARCHAR(100) NOT NULL,
    address TEXT,
    contact_number VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, branch_code)
);

-- 2. Jabatan
CREATE TABLE departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    dept_code VARCHAR(20) NOT NULL,
    dept_name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, dept_code)
);

-- 3. Pengguna
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE SET NULL,
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL,
    phone VARCHAR(20),
    password_hash VARCHAR(255) NOT NULL,           -- argon2id / bcrypt
    role VARCHAR(30) NOT NULL DEFAULT 'STAFF',     -- SUPER_ADMIN, TENANT_ADMIN, MANAGER, STAFF
    voice_profile_id VARCHAR(100),
    voice_consent_at TIMESTAMPTZ,                  -- PDPA: persetujuan rakaman suara
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (tenant_id, email)                      -- email sama dibenarkan di tenant berbeza
);

-- 4. Refresh token / sesi peranti
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    device_type VARCHAR(10) NOT NULL,              -- WEB, MOBILE
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Konfigurasi API ejen peringkat syarikat (default)
CREATE TABLE tenant_agent_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    provider VARCHAR(30) NOT NULL,                 -- HERMES, STAFFBOT, OPENAI, ANTHROPIC, CUSTOM
    endpoint_url TEXT,
    api_key_encrypted BYTEA NOT NULL,              -- AES-256-GCM
    api_key_last4 VARCHAR(4),
    default_model VARCHAR(100),
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 6. Konfigurasi API ejen peringkat staf (override)
CREATE TABLE user_agent_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider VARCHAR(30) NOT NULL,
    endpoint_url TEXT,
    api_key_encrypted BYTEA NOT NULL,
    api_key_last4 VARCHAR(4),
    model VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 7. SOP (dokumen) + chunks untuk RAG
CREATE TABLE sop_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    source_file_url TEXT,
    version INT DEFAULT 1,
    status VARCHAR(20) DEFAULT 'PROCESSING',       -- PROCESSING, READY, FAILED
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE sop_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES sop_documents(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),                        -- ikut model embedding yang dipilih
    embedding_model VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON sop_chunks USING hnsw (embedding vector_cosine_ops);

-- 8. Ejen (per jabatan)
CREATE TABLE ai_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    agent_name VARCHAR(100) NOT NULL,
    system_prompt TEXT NOT NULL,
    model_name VARCHAR(100),
    allowed_tools JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 9. Kebenaran tool mengikut peranan
CREATE TABLE role_tool_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role VARCHAR(30) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    can_execute BOOLEAN DEFAULT TRUE,
    requires_approval BOOLEAN DEFAULT FALSE,
    UNIQUE (tenant_id, role, tool_name)
);

-- 10. Kelulusan
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id),
    requested_by UUID NOT NULL REFERENCES users(id),
    tool_name VARCHAR(100) NOT NULL,
    tool_payload JSONB NOT NULL,
    summary TEXT NOT NULL,                         -- ringkasan untuk pelulus
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED, EXECUTED, FAILED, EXPIRED
    decided_by UUID REFERENCES users(id),
    decided_at TIMESTAMPTZ,
    result JSONB,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 11. Sesi & mesej
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id),
    agent_id UUID REFERENCES ai_agents(id),
    session_title VARCHAR(150) DEFAULT 'Perbualan Baru',
    interaction_mode VARCHAR(20) DEFAULT 'TEXT',   -- VOICE, TEXT
    is_closed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL,              -- USER, AGENT, SYSTEM, TOOL
    content TEXT NOT NULL,
    audio_file_url TEXT,                           -- dipadam ikut data_retention_days
    latency_ms INT,
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 12. Peranti untuk push notification
CREATE TABLE device_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform VARCHAR(10) NOT NULL,                 -- ANDROID, IOS, WEB
    push_token TEXT NOT NULL,
    last_seen_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, push_token)
);

-- 13. Penggunaan (untuk billing & kos)
CREATE TABLE usage_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    usage_type VARCHAR(30) NOT NULL,               -- LLM_TOKENS_IN, LLM_TOKENS_OUT, STT_SECONDS, TTS_CHARS
    quantity NUMERIC NOT NULL,
    key_source VARCHAR(20) NOT NULL,               -- USER, TENANT, MANAGED
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 14. Audit
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    branch_id UUID REFERENCES branches(id) ON DELETE SET NULL,
    action_type VARCHAR(100) NOT NULL,             -- LOGIN, UPDATE_API_KEY, TOOL_CALL, APPROVE, ...
    details JSONB NOT NULL,                        -- JANGAN simpan API key / password
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## 3.8 API endpoints (v2)

Semua di bawah `/api/v1`. Semua endpoint (kecuali login dan refresh) perlukan `Authorization: Bearer <JWT>`. Tenant **sentiasa** diambil dari JWT, **tidak pernah** dari body atau query.

**Auth**

| Method | Endpoint | Nota |
| :--- | :--- | :--- |
| POST | `/auth/login` | Body: `{ tenant_code \| (subdomain dari Host), email, password, device_type }` |
| POST | `/auth/refresh` | Putar refresh token |
| POST | `/auth/logout` | Batalkan refresh token |
| GET | `/me` | Profil, peranan, cawangan, jabatan |

**Chat dan suara**

| Method | Endpoint | Nota |
| :--- | :--- | :--- |
| GET/POST | `/sessions` | Senarai dan cipta sesi |
| GET | `/sessions/{id}/messages` | Sejarah |
| POST | `/sessions/{id}/messages` | Hantar teks; respons streaming (SSE) |
| POST | `/voice/transcribe` | `multipart/form-data` (wav/webm/m4a), kemudian `{ transcript }` |
| POST | `/voice/speak` | `{ text }`, kemudian audio (Fasa 2) |
| WSS | `/ws/v1/voice-stream` | PCM 16 kHz masuk; token teks + audio TTS keluar (Fasa 2) |

**Kelulusan**

| Method | Endpoint | Nota |
| :--- | :--- | :--- |
| GET | `/approvals?status=PENDING` | Ikut skop peranan |
| POST | `/approvals/{id}/approve` | MANAGER / TENANT_ADMIN |
| POST | `/approvals/{id}/reject` | MANAGER / TENANT_ADMIN |

**Admin syarikat** (`TENANT_ADMIN`)

| Method | Endpoint | Nota |
| :--- | :--- | :--- |
| CRUD | `/admin/branches`, `/admin/departments`, `/admin/users` | |
| PUT | `/admin/agent-config` | Simpan API default syarikat (write-only) |
| POST | `/admin/agent-config/test` | Uji sambungan tanpa mendedahkan kunci |
| PUT | `/admin/users/{id}/agent-credentials` | Simpan API staf (write-only) |
| DELETE | `/admin/users/{id}/agent-credentials` | Kembali ke default syarikat |
| POST | `/admin/sop` | Upload; diproses async |
| CRUD | `/admin/agents`, `/admin/tool-permissions` | |
| GET | `/admin/usage`, `/admin/audit-logs` | Laporan |

**Peranti:** `POST /devices` dan `DELETE /devices/{id}` untuk push token.

**Super Admin:** `/platform/tenants` (CRUD, suspend) dan `/platform/usage`.

## 3.9 UI dan wireframe

**Web (desktop):** kekalkan layout PRD asal, dengan tambahan:

- **Menu Admin:** Cawangan, Jabatan, Staf, Tetapan Ejen (API), SOP, Kebenaran Tool, Laporan, Audit.
- **Panel Kelulusan:** senarai permintaan tertunggak, dengan butang Lulus/Tolak.
- **Indikator suara:** hijau (mendengar wake word secara lokal), merah (sedang menghantar audio ke server).

**Mobile:** skrin utama mengikut wireframe PRD asal (lingkaran suara + transkrip), dengan tambahan:

- **Butang besar tekan-dan-tahan** sebagai mod default.
- **Toggle "Hands-free"** (Fasa 2), dengan amaran bahawa mod ini hanya aktif semasa app dibuka.
- **Tab:** Chat, Kelulusan (untuk pengurus), Sejarah, Profil.
- **Skrin login:** kod syarikat, email, password.

## 3.10 Keperluan bukan fungsian (NFR)

| Kategori | Sasaran |
| :--- | :--- |
| Latency push-to-talk | Transkrip < 3 s untuk audio 10 s |
| Latency respons teks | Token pertama < 2 s (tanpa tool call) |
| Latency suara streaming (Fasa 2) | Audio respons pertama < 1.5 s selepas pengguna berhenti bercakap |
| Pengguna serentak (MVP) | 50 per tenant, 500 keseluruhan |
| Uptime | 99.5% (MVP), 99.9% (SLA berbayar) |
| Keselamatan transit | TLS 1.3, WSS sahaja |
| Keselamatan at-rest | API key AES-256-GCM; password argon2id/bcrypt; backup disulitkan |
| Pengasingan | Tenant dan cawangan dikuatkuasakan di query backend dan tool MCP |
| Rate limit | Per user dan per tenant (Redis) |
| Backup | DB harian, simpanan 14 hari, ujian restore bulanan |
| Pemantauan | Uptime, ralat, latency STT/LLM/TTS, kos per tenant |

## 3.11 Privasi suara dan PDPA

1. **Tiada audio keluar sebelum wake word** dikesan di peranti (Fasa 2). Dalam mod push-to-talk, audio hanya dihantar semasa butang ditekan.
2. Penimbal audio lokal dipadam setiap 5 saat jika wake word tidak dikesan.
3. **Indikator visual wajib** semasa audio dihantar ke server.
4. **Persetujuan rakaman suara** diminta semasa kali pertama guna suara, dan direkod dalam `users.voice_consent_at`.
5. Fail audio **dipadam secara automatik** selepas `tenants.data_retention_days`. Transkrip teks boleh disimpan lebih lama mengikut tetapan tenant.
6. Hak pengguna untuk meminta salinan dan pemadaman data (PDPA 2010).
7. API key, password dan token **tidak pernah** ditulis dalam log, audit atau mesej ralat.

## 3.12 Model bisnes (dari PRD asal, harga masih perlu diisi oleh Remy)

| Komponen | Pakej Setup (sekali) | Langganan Bulanan (SLA) |
| :--- | :--- | :--- |
| Skop | Setup VPS/container, DB dan Redis; konfigurasi ejen dan MCP; web + mobile build; konfigurasi 1–3 SOP jabatan; latihan staf 1 hari | Pemantauan 24/7; patch keselamatan; kemas kini prompt ikut SOP baharu; backup harian; sokongan tiket |
| Harga | **[ISI]** | **[ISI]**: cadang ikut bilangan staf + kuota minit suara |
| Kos tambahan | Lesen wake word (jika Porcupine); akaun Apple/Google developer | Kos LLM/STT/TTS jika guna kunci terurus (kurang jika klien guna BYOK) |

---

# BAHAGIAN 4 — ARAHAN UNTUK CLAUDE CODE

## 4.1 Peraturan keselamatan (WAJIB)

1. **Fasa 0 adalah BACA SAHAJA.** Jangan ubah, padam, restart, deploy, `docker stop/rm`, `git push`, migrate DB, atau edit sebarang fail di server production.
2. **Jangan paparkan rahsia.** Bila membaca `.env`, config atau DB, tutup (mask) semua API key, password, token dan secret (contoh: `sk-...a1b2`). Jangan salin rahsia ke dalam laporan.
3. **Jangan query data pelanggan sebenar** melebihi yang perlu. Untuk struktur DB, guna `\d`, `information_schema`, atau `SELECT count(*)`, bukan `SELECT *` pada data klien.
4. **Guna SSH key sedia ada sahaja.** Jangan minta atau simpan password server.
5. Sebarang perubahan selepas Fasa 0 dibuat di **repo/branch baharu dan persekitaran staging**, dan hanya selepas Remy meluluskan pelan.
6. Jika ragu-ragu, **berhenti dan tanya Remy**.

## 4.2 Fasa 0 — Discovery (baca sahaja)

**Matlamat:** Cari server StaffBot, fahami seni binanya, dan bandingkan dengan PRD v2.

**Langkah:**

1. **Cari server.**
   - Jalankan `nslookup staffbot.my` (atau `dig`) untuk mendapatkan IP.
   - Semak `~/.ssh/config` dan senarai host yang Remy ada.
   - Padankan IP dengan host, atau SSH ke setiap host dan cari `staffbot` dalam config Nginx/Apache (`/etc/nginx`, `/www/server/panel/vhost` untuk aaPanel), `docker ps`, dan folder web (`/var/www`, `/www/wwwroot`, `/home/*`).
2. **Petakan deployment.**
   - Panel yang digunakan (aaPanel/ServerAvatar/cPanel/manual).
   - Senarai container (`docker ps --format`), image, port, volume, network.
   - Bagaimana subdomain klien dihalakan ke container masing-masing (Nginx wildcard? config dijana automatik?).
   - Bagaimana container klien baharu dicipta (skrip, template compose, API?).
3. **Petakan kod.**
   - Lokasi source code, bahasa dan framework (backend, frontend), versi.
   - Struktur folder utama dan entry point.
   - Repo git (remote, branch). Jangan pull atau push.
4. **Petakan data.**
   - Jenis DB (PostgreSQL/MySQL/SQLite?), satu DB berkongsi atau satu DB per klien?
   - Senarai jadual dan struktur (terutama: users, companies/tenants, API keys, agents, SOP/knowledge, conversations, memory).
   - Bagaimana API key BYOK disimpan (plaintext? disulitkan? di mana?).
5. **Petakan auth dan API.**
   - Mekanisme login (session, JWT, lain-lain), di `customer/login.html` dan backend.
   - Senarai endpoint API sedia ada (route files).
   - Adakah ada API awam/dalaman yang boleh dipanggil oleh mobile app?
6. **Petakan ejen AI.**
   - Enjin ejen yang digunakan (Hermes Agent? OpenClaw? custom?), dan cara ia dipanggil.
   - Bagaimana SOP dimuatkan (RAG? vektor?), bagaimana memori disimpan.
   - Integrasi saluran (WhatsApp, Telegram): library/servis apa.
7. **Infra lain.** Redis/queue, cron/worker, backup, SSL, sumber server (CPU/RAM/disk), anggaran bilangan klien aktif (count sahaja).

**Output Fasa 0:** tulis fail **`DISCOVERY_REPORT.md`** dengan bahagian berikut:

```
1. Ringkasan (5–10 ayat)
2. Server: penyedia, IP, OS, panel, sumber (rahsia ditutup)
3. Deployment: container, routing subdomain, cara provision klien baharu
4. Tech stack: backend, frontend, DB, cache, ejen AI, versi
5. Struktur kod: folder utama dan fungsinya
6. Skema DB: jadual dan lajur utama (tiada data klien)
7. Auth & API: mekanisme login, senarai endpoint
8. Ejen AI: enjin, cara panggilan, SOP/RAG, memori, BYOK
9. Integrasi: WhatsApp, Telegram, Drive, dll.
10. Analisis jurang: StaffBot sedia ada vs PRD v2 (Bahagian 3), dalam bentuk jadual
    | Keperluan PRD v2 | Sudah ada? | Di mana | Perlu tambah/ubah |
11. Risiko & isu keselamatan yang ditemui (cth: API key plaintext)
12. Cadangan seni bina muktamad:
    - Lanjutkan StaffBot, atau servis berasingan?
    - Di mana jadual tenant patut duduk (C7)?
    - Stack untuk lapisan suara
13. Jawapan kepada soalan S1–S9 yang boleh dijawab dari kod; selebihnya senaraikan untuk Remy
```

**Berhenti selepas Fasa 0** dan minta Remy menyemak `DISCOVERY_REPORT.md` sebelum meneruskan.

## 4.3 Fasa 0.5 — Pelan pelaksanaan (selepas Remy setuju)

- Kemas kini PRD v2 (Bahagian 3) berdasarkan penemuan: buang yang sudah ada, guna nama jadual dan endpoint sebenar.
- Tulis **`IMPLEMENTATION_PLAN.md`**:
  - Seni bina muktamad + diagram.
  - Migrasi DB (skrip migration, tiada perubahan terus ke prod).
  - Senarai tugasan Fasa 1 dengan anggaran masa.
  - Persediaan staging (container StaffBot salinan + DB ujian).
  - Strategi ujian (unit, integrasi, ujian suara BM).
- Dapatkan kelulusan Remy.

## 4.4 Fasa 1 dan seterusnya — Pembangunan

Urutan cadangan untuk Fasa 1 (rujuk Bahagian 3.4):

1. Migrasi DB: tenant, cawangan, jabatan, credentials (F1.2–F1.5).
2. Auth API dengan JWT tenant-aware + refresh token (F1.1).
3. Penghala ejen: resolusi kunci staf → syarikat, penyulitan kunci (F1.4–F1.5).
4. Chat teks + streaming (F1.6).
5. `POST /voice/transcribe` dengan Whisper; uji 20+ rakaman BM/Manglish (F1.7).
6. SOP upload → chunks → embedding → RAG (F1.8).
7. Audit + usage logging (F1.9–F1.10).
8. Web: skrin admin + chat + push-to-talk.
9. Mobile Flutter (Android dahulu): login, chat, push-to-talk.
10. Ujian keselamatan: pengasingan tenant/cawangan, kebocoran kunci, rate limit.

**Definisi siap (Definition of Done) untuk setiap tugasan:**

- Kod di branch, dengan ujian lulus.
- Tiada rahsia dalam kod atau log.
- Dokumentasi endpoint dikemas kini.
- Didemo di staging.

## 4.5 Konvensyen

- Bahasa dokumentasi: Bahasa Melayu (istilah teknikal dalam English).
- Commit: kecil, satu perubahan logik setiap commit, mesej jelas.
- Rahsia hanya dalam `.env` (tidak di-commit); sediakan `.env.example`.
- Semua query mesti ditapis oleh `tenant_id` (dan `branch_id` untuk STAFF/MANAGER). Tambah ujian yang membuktikan pengguna tenant A tidak dapat melihat data tenant B.

---

## LAMPIRAN A — Contoh tool MCP (dari PRD asal)

```json
{
  "name": "query_branch_inventory",
  "description": "Dapatkan baki inventori bagi produk tertentu di cawangan yang dipilih mengikut SOP.",
  "parameters": {
    "type": "object",
    "properties": {
      "branch_code": { "type": "string", "description": "Kod cawangan, contoh: BR-KLG-01" },
      "sku": { "type": "string", "description": "Kod SKU barangan" }
    },
    "required": ["branch_code", "sku"]
  }
}
```

**Nota v2:** backend mesti mengesahkan bahawa `branch_code` adalah cawangan pengguna (atau pengguna ialah TENANT_ADMIN) **sebelum** tool dilaksanakan. Jangan percaya parameter yang dijana oleh LLM.

## LAMPIRAN B — Seni bina asal (PRD v1, untuk rujukan)

```
[Pengguna Cawangan (Web / Mobile App)]
        │
   (Mikrofon Sentiasa Pantau secara Tempatan: On-Device WASM / Porcupine)
        │
   [Pengesanan "Wake Word" Berjaya!] (cth: "Hey Hermes")
        │
        ▼ (Audio Dihantar via WebSocket / REST)
[Cloud Gateway / Nginx Reverse Proxy (TLS 1.3)]
        │
        ▼ (Auth Token / JWT Bearer Validation)
[Backend FastAPI Orchestrator]
   ├── 1. Modul STT (Whisper Audio -> Teks)
   ├── 2. Pengambilan Konteks Syarikat / Cawangan (PostgreSQL + RAG)
   ├── 3. Hermes AI Agent Orchestrator
   │       ├── Pemilihan Ejen Jabatan (Finance, HR, Operations, Logistik)
   │       └── MCP Client (Model Context Protocol)
   │               └── [MCP Server 1: SQL Database]
   │               └── [MCP Server 2: File System / SOP Documents]
   │               └── [MCP Server 3: ERP / Sistem Cawangan Luaran]
   ├── 4. Hantar Perintah ke LLM (OpenAI / Claude / Self-hosted Llama 3)
   ├── 5. Hasil Respons -> Modul TTS (Teks -> Audio Suara)
   └── 6. Simpan Log Audit & Transaksi ke PostgreSQL
        │
        ▼ (Balas Teks + Audio Stream)
[Frontend Web / Mobile App Main Balik Respons]
```

## LAMPIRAN C — Prompt permulaan untuk Claude Code

Salin dan tampal ke Claude Code bersama fail ini:

> Baca `HERMES_VOICE_PROJECT_BRIEF.md` sepenuhnya. Mulakan **Fasa 0 (Discovery)** mengikut Bahagian 4.2, dan patuhi semua peraturan dalam Bahagian 4.1. Mod adalah **baca sahaja**: jangan ubah apa-apa di mana-mana server. Tutup semua rahsia dalam output. Hasilkan `DISCOVERY_REPORT.md` mengikut format yang ditetapkan, kemudian berhenti dan tunggu semakan saya.
