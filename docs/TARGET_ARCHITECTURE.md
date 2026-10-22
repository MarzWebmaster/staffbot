# Seni Bina Sasaran — StaffBot.my (Managed Hermes Agent)

> Versi 1.0, 22 Okt 2026. Status: **dipersetujui secara prinsip oleh Remy**. Angka pakej dan perkara di §12 masih perlu dimuktamadkan.
> Dokumen berkaitan: `ARCHITECTURE.md` (keadaan sekarang), `SECURITY_FINDINGS.md`, `GAP_ANALYSIS_HERMES_HUB.md`.
> **[SAHKAN-HERMES]** = andaian tentang keupayaan Hermes Agent yang perlu diuji dengan versi yang dipilih.

## 1. Ringkasan

StaffBot.my ialah **Hermes Agent yang diurus oleh provider (Marz)**.

- Pelanggan daftar pakej, kemudian mendapat **Hermes Agent sendiri dalam container sendiri**. Pengalamannya sama seperti memasang Hermes dalam VPS sendiri.
- Kita yang urus server, upgrade, backup dan keselamatan.
- Semua LLM menggunakan pakej kita (token terurus) atau BYOK pelanggan.
- Ada guardrail default dari kita.
- Ciri yang boleh digunakan dihadkan ikut pakej.

## 2. Keputusan (Decision Log)

| # | Keputusan | Sebab |
| :--- | :--- | :--- |
| D1 | **Satu container Hermes penuh untuk setiap pelanggan** (satu image, banyak container) | Hermes direka sebagai ejen untuk seorang pengguna, dengan memori, skill dan fail dalam satu `HERMES_HOME`. Satu Hermes yang dikongsi tidak dapat mengasingkan data pelanggan dengan selamat apabila tool terminal/fail hidup |
| D2 | **Ditolak:** satu Hermes untuk semua pelanggan | Satu prompt injection dengan tool terminal boleh membaca data syarikat lain; satu crash menjatuhkan semua pelanggan |
| D3 | **Ditolak (buat masa ini):** VM penuh per pelanggan (Firecracker) | Terlalu kompleks untuk diurus pada tahap ini. Container + gVisor sudah memadai |
| D4 | **Semua kawalan penting di LUAR container** | Pelanggan ada terminal dan boleh mengubah apa-apa di dalam container. Had yang diletak di dalam container boleh dipintas |
| D5 | **Kunci LLM tidak pernah masuk ke container.** Semua panggilan LLM melalui **LLM proxy** kita | Kuota, billing, BYOK dan guardrail dikuatkuasakan di satu tempat; tiada kunci yang boleh dicuri dari container |
| D6 | **Guardrail default dikuatkuasakan di LLM proxy** (tapis input + output, suntik polisi sistem) | Tidak boleh dimatikan dari dalam container |
| D7 | **Tools dan skills dalam 3 lapis: Teras / Katalog / Custom** (§6) | Default yang selamat dari kita, pilihan yang diuji, dan kebebasan pelanggan dalam sempadan container |
| D8 | **gVisor (`runsc`)** sebagai runtime container pelanggan | Pelanggan diberi shell; gVisor mengasingkan kernel host |
| D9 | **Pisahkan program dan data:** Hermes dalam image (versi ditetapkan), data dalam volume `HERMES_HOME` | Upgrade bermakna menukar image sahaja; data pelanggan tidak disentuh |
| D10 | **Versi Hermes ditetapkan (pin)**, tidak menggunakan "latest". Upgrade melalui staging, kemudian canary, kemudian rolling | Kawalan penuh dan boleh rollback |
| D11 | **Scale-to-zero:** container tidur bila idle, dan bangun bila ada mesej | Jimat RAM. "Sentiasa hidup" dijadikan ciri pakej tinggi |
| D12 | **Pelanggan tidak boleh upgrade Hermes sendiri** | Versi managed; kita kawal kestabilan |
| D13 | **Container pelanggan diletak dalam server khusus**, bukan server OVH yang dikongsi dengan mail server dan pandaibot. Reka bentuk sedia untuk berbilang node | Keselamatan dan kapasiti |
| D14 | **Satu control plane** (`staffbot-api`) untuk login, billing, admin dan provisioning | Satu sistem auth; mobile dan web memanggil API yang sama |
| D15 | **Saluran (WhatsApp/Telegram/Web) melalui channel router pusat**, yang menghantar mesej ke container pelanggan | Satu titik untuk wake-on-message, kuota dan audit |
| D16 | **Buang tiga enjin AI berlebihan.** `server-b/gateway` dikecilkan menjadi LLM proxy + channel router; logik ReAct-nya digantikan oleh Hermes | Kurangkan kod yang perlu diselenggara |
| D17 | **Pelanggan mengurus Hermes melalui Web Console dalam Portal Pelanggan** (Hermes CLI), bukan SSH | Satu login, tiada port atau key SSH, sesi diaudit, akses ikut pakej (§7A) |
| D18 | **Dua portal: Superadmin dan Pelanggan.** Semua atribut pakej boleh di-CRUD oleh superadmin tanpa ubah kod | Pakej boleh dilaras mengikut pasaran (§7.1) |

## 3. Gambaran seni bina

```
                      Cloudflare (DNS, CDN, WAF)
                               │
        ┌──────────────────────┴───────────────────────────────────────┐
        │                 CONTROL PLANE (milik kita)                     │
        │                                                                │
        │  staffbot-api ........ login, billing (Stripe), admin, pakej,  │
        │                        provisioning, BYOK (disulitkan)         │
        │  channel-router ...... Web chat / WhatsApp (Baileys) / Telegram│
        │                        → bangunkan & hantar ke container betul │
        │  llm-proxy ........... SATU-SATUNYA jalan ke LLM               │
        │                        • semak token per-pelanggan             │
        │                        • model dibenarkan ikut pakej           │
        │                        • kuota token / BYOK                    │
        │                        • guardrail input + output              │
        │                        • log penggunaan & audit                │
        │  orchestrator ........ cipta / tidur / bangun / upgrade /      │
        │                        backup container                        │
        │  Postgres ............ data platform (bukan data Hermes)       │
        └───────────────┬──────────────────────────────▲─────────────────┘
                        │ mesej (token per-pelanggan)   │ panggilan LLM sahaja
        ┌───────────────▼──────────────────────────────┴─────────────────┐
        │          NODE PELANGGAN (server khusus, boleh >1)               │
        │                                                                 │
        │  hermes-c1        hermes-c2        …        hermes-cN           │
        │  ┌────────────┐  ┌────────────┐            ┌────────────┐       │
        │  │Hermes penuh│  │Hermes penuh│            │Hermes penuh│       │
        │  │runtime gVisor│ │            │            │            │       │
        │  └─────┬──────┘  └─────┬──────┘            └─────┬──────┘       │
        │   vol HERMES_HOME  vol HERMES_HOME           vol HERMES_HOME    │
        │   config asas RO   config asas RO            config asas RO     │
        │                                                                 │
        │  Firewall host: blok rangkaian dalaman, Tailscale, metadata,    │
        │  port 25; benarkan internet + llm-proxy                         │
        └─────────────────────────────────────────────────────────────────┘
```

## 4. Komponen

| Komponen | Peranan | Dari kod sekarang |
| :--- | :--- | :--- |
| `staffbot-api` | Control plane: auth, billing, pakej, admin, provisioning, simpan BYOK (disulitkan) | `api/` (kekal; dikemas) |
| `llm-proxy` | Proksi serasi OpenAI. Mengesahkan token per pelanggan, memilih kunci (BYOK atau terurus), menguatkuasakan model dan kuota pakej, guardrail, dan log | Dikecilkan dari `server-b/gateway/main.py` (`/v1/chat/completions`, kuota, `token_usage_log`) + `content_moderation.py` |
| `channel-router` | Menerima mesej Web/WhatsApp/Telegram, membangunkan container jika tidur, dan menghantar ke API Hermes pelanggan | `server-b/gateway` (bahagian `/api/incoming/*`) + `baileys-manager` + `telegram-manager` |
| `orchestrator` | Cipta, tidur, bangun, upgrade, backup dan padam container | `api/app/services/docker_service.py` + `deployment_service.py` (dilanjutkan) |
| `hermes-client` image | Hermes Agent (versi ditetapkan) + tool teras StaffBot + config asas | `hermes-core/` (dihidupkan semula) |
| Postgres | Data platform: klien, langganan, penggunaan, audit, konfigurasi | `staffbot-db` |

**Akan dibuang selepas peralihan:** `hermes-gateway/`, `server-b/core-image/`, `sandbox/`, `server-b/hybrid-brain/`, `api/app_old/`, fail `.bak`, skrip patch sekali guna dalam `scripts/`, dan logik ReAct/tool dalam gateway.

## 5. Keselamatan dan pengasingan

### 5.1 Lapisan kawalan (semuanya di luar jangkauan pelanggan)

| Kawalan | Mekanisme |
| :--- | :--- |
| Pengasingan kernel | gVisor `runsc` |
| Keistimewaan | `cap_drop ALL`, `no-new-privileges`, bukan root, tiada `privileged`, **tiada `docker.sock`** |
| Sumber | Had CPU, RAM, PID dan disk (quota volume) ikut pakej |
| Rangkaian keluar | Firewall host: **blok** `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10` (Tailscale), `169.254.0.0/16`, `127.0.0.0/8`, port 25. **Benarkan** internet awam + `llm-proxy` |
| Rangkaian antara pelanggan | Satu rangkaian Docker per pelanggan; tiada laluan antara container |
| Kunci LLM | Disimpan dalam control plane sahaja (disulitkan). Container hanya memegang **token per pelanggan** untuk `llm-proxy` |
| Token per pelanggan | HMAC per `client_id` (sudah dilaksanakan dalam pembetulan S-05); boleh dibatalkan |
| Config asas | Fail config asas di-mount **read-only**: endpoint LLM = `llm-proxy`, toolset ikut pakej, polisi. **[SAHKAN-HERMES]** cara Hermes menggabungkan config asas dengan config pelanggan |
| Guardrail | Di `llm-proxy`: moderasi input (regex + AI), tapisan output, polisi sistem yang disuntik pada setiap panggilan |
| Audit | Setiap panggilan LLM, tindakan admin dan perubahan pakej direkod dalam `audit_trail` |

### 5.2 Apa yang dianggap "bahaya" (dimatikan untuk semua pakej)
- Akses ke host, Docker dan rangkaian dalaman (disekat oleh mekanisme di atas, bukan oleh Hermes).
- Toolset Hermes yang memerlukan akses host atau desktop, contohnya `computer_use` **[SAHKAN-HERMES]** senarai penuh toolset untuk versi yang dipilih.
- Menghantar email terus melalui port 25 (mesti melalui SMTP pelanggan atau relay kita yang ada had).

## 6. Tools dan skills: model 3 lapis

| Lapis | Disediakan oleh | Pelanggan | Contoh |
| :--- | :--- | :--- | :--- |
| **1. Teras** | Kita; dipasang dalam image | Tidak boleh buang | Tool StaffBot: webhook (`call_webhook`), email, tugasan, saluran WhatsApp/Telegram, polisi guardrail |
| **2. Katalog** | Kita pilih dan uji | Hidup/matikan sendiri dari dashboard, ikut pakej | Dokumen (Word/Excel/PPT), carian web, browser, Google Drive, ERPNext, WordPress, HubSpot |
| **3. Custom** | Pelanggan | Tambah sendiri, ikut pakej | Skill teks (SOP, persona, arahan): **semua pakej**. Kod / MCP server sendiri: **pakej tinggi sahaja** |

Prinsip: **sempadan keselamatan ialah container + firewall + proxy, bukan senarai skill.** Skill custom berjalan dalam container pelanggan sendiri; jika ia rosak, hanya container pelanggan itu yang terjejas.

Tool StaffBot sedia ada (webhook, carian, email, tugasan dalam `server-b/gateway`) dipindahkan ke **plugin/MCP server** dalam image Hermes. **[SAHKAN-HERMES]** sama ada mekanisme plugin atau MCP lebih sesuai.

## 7. Pakej (cadangan v1, 22 Okt 2026 — Remy akan laraskan)

| | Percubaan | Starter | Professional | Enterprise |
| :--- | :--- | :--- | :--- | :--- |
| Harga / bulan | Percuma 7 hari | RM49 | RM149 | RM499 |
| AI Staff (ejen) | 1 | 1 | 3 | 10 |
| Token terurus / bulan | 200k | 2M | 8M | 30M |
| Model LLM | Ekonomi | Ekonomi | + Premium (terhad) | Semua |
| BYOK | ✖ | ✔ | ✔ | ✔ |
| Saluran | Web | Web + 1 WhatsApp + Telegram | + 2 WhatsApp | + 5 WhatsApp |
| Web Console (Hermes CLI) | ✖ | ✔ `hermes` sahaja | ✔ shell penuh | ✔ shell penuh |
| Ejen boleh guna terminal / kod | ✖ | ✖ | ✔ | ✔ |
| Lapis 1 Teras | ✔ | ✔ | ✔ | ✔ |
| Lapis 2 Katalog | Asas | Asas (±20) | Semua | Semua |
| Lapis 3 Skill custom (teks/SOP) | ✔ | ✔ | ✔ | ✔ |
| Lapis 3 Kod / MCP custom | ✖ | ✖ | ✔ | ✔ |
| CPU / RAM / Disk | 0.5 / 1 GB / 2 GB | 0.5 / 1 GB / 5 GB | 1 / 2 GB / 20 GB | 2 / 4 GB / 50 GB |
| Tidur selepas idle | 15 min | 30 min | 60 min | Sentiasa hidup |
| Simpanan backup | — | 7 hari | 14 hari | 30 hari |
| Pilih masa upgrade | ✖ | ✖ | ✖ | ✔ |
| Sokongan | — | Email | Email + WhatsApp | Keutamaan |

**Nota:**
- **Token.** Hermes ialah ejen yang memanggil tool berulang kali dengan system prompt yang panjang, jadi satu tugasan boleh menggunakan puluhan ribu token. Kuota 100k/500k/2M dalam sistem sekarang terlalu kecil. Angka di atas mengandaikan model ekonomi (cth DeepSeek). **Semak harga penyedia dan margin sebelum muktamad.**
- **Pilihan:** kira kuota dalam **kredit RM**, bukan token, kerana harga setiap model berbeza.
- **AI Staff berbilang** dalam satu container menggunakan profil Hermes. **[SAHKAN-HERMES]**
- **"Web Console `hermes` sahaja"** bermaksud console menjalankan `hermes` terus, bukan bash. **[SAHKAN-HERMES]** sama ada CLI Hermes membenarkan pelarian ke shell.

**Bagaimana had pakej dikuatkuasakan:**
- model dan token: di `llm-proxy`;
- CPU, RAM dan disk: di Docker;
- toolset: dalam config asas read-only;
- console: di control plane;
- tidur/hidup: di orchestrator.

### 7.1 Superadmin CRUD pakej

- **Setiap baris dalam jadual di atas ialah medan dalam jadual `packages`**, dan boleh dicipta, dibaca, dikemas kini dan dipadam dari Portal Superadmin, tanpa mengubah kod.
- Medan baharu yang perlu ditambah (migrasi Alembic): `ai_staff_limit`, `allowed_models`, `channel_limits`, `byok_allowed`, `console_mode` (none/hermes/shell), `agent_terminal`, `catalog_tier`, `custom_code_allowed`, `idle_sleep_minutes` (null = sentiasa hidup), `backup_retention_days`, `upgrade_window`, `support_level`.
- CRUD sedia ada (`api/app/routers/admin/packages.py`, `static/admin/packages.html`) diguna semula. **Bug B-11 mesti dibetulkan dahulu.**
- Apabila pakej dikemas kini, orchestrator menjana semula config asas dan had sumber untuk semua pelanggan pakej itu (berperingkat, seperti rolling update).
- Pakej yang masih ada pelanggan tidak boleh dipadam; ia hanya boleh dinyahaktifkan (`is_active=false`, tidak dipaparkan kepada pelanggan baharu).

## 7A. Portal dan akses

| Pengguna | Antara muka | Fungsi |
| :--- | :--- | :--- |
| **Superadmin (Marz)** | Portal Superadmin (web) | CRUD pakej; urus pelanggan; penyedia LLM + harga model; katalog skill/tool; polisi guardrail; versi Hermes + rollout (canary/rolling); status, sumber dan log container; billing; audit |
| **Pelanggan** | Portal Pelanggan (web) | Langganan dan bayaran; dashboard penggunaan (token, kredit, saluran); BYOK; sambung WhatsApp (QR) dan Telegram; hidup/matikan skill katalog; skill custom; senarai AI Staff; chat web |
| **Pelanggan** | **Web Console** dalam portal, yang menjalankan **Hermes CLI** | Urus Hermes Agent sendiri seperti dalam VPS sendiri |

**Web Console (keputusan D17):**
- Terminal dalam browser (xterm.js) melalui WebSocket, kemudian `docker exec` ke container pelanggan. Login menggunakan akaun portal yang sama.
- Tiada port SSH dibuka dan tiada SSH key per pelanggan.
- Setiap sesi direkod dalam audit (siapa dan bila); sesi tamat selepas idle.
- Mod ikut `packages.console_mode`: `none` / `hermes` (jalankan `hermes` sahaja) / `shell` (bash penuh dalam container).
- Membuka console akan membangunkan container jika ia sedang tidur.
- SSH sebenar boleh ditawarkan kemudian untuk Enterprise sahaja (keputusan masa depan).

## 8. LLM, BYOK dan kuota

1. Hermes dalam container memanggil `llm-proxy` (endpoint serasi OpenAI) dengan token per pelanggan. **[SAHKAN-HERMES]** Hermes menyokong `custom_providers` dengan `base_url` tersuai. Repo sekarang sudah menggunakannya.
2. Proxy mengenal pasti pelanggan dari token, kemudian memilih kunci:
   - **BYOK** jika pelanggan menyimpannya dan menghidupkannya. Kuota terurus tidak dipotong.
   - Jika tidak, **kunci terurus kita**, dan kuota pakej disemak.
3. Proxy menyemak bahawa model yang diminta dibenarkan oleh pakej. Jika tidak, ia menukar ke model default pakej, atau menolak.
4. Guardrail input, kemudian LLM, kemudian guardrail output.
5. Token direkod untuk **setiap** pusingan (termasuk pusingan tool), dan kuota dipotong.
6. Pelanggan melihat penggunaan di dashboard. Amaran dihantar pada 80% dan 100%.

## 9. Kitar hayat container

| Peristiwa | Tindakan orchestrator |
| :--- | :--- |
| Bayaran berjaya / admin deploy | Cipta volume `HERMES_HOME` + container dari image versi semasa; jana config asas ikut pakej; jana token per pelanggan; daftar laluan di channel-router |
| Idle > N minit (cth 30) | Hentikan container (volume kekal) |
| Mesej masuk (mana-mana saluran) | Bangunkan container. Mesej ditahan sehingga container sedia. Sasaran: < 10 s **[ukur]** |
| Tukar pakej | Jana semula config asas + had sumber; restart container |
| Langganan tamat / digantung | Hentikan container; volume disimpan N hari; kemudian arkib dan padam (PDPA) |
| Padam akaun | Arkib volume (`.tar.gz` disulitkan), padam container, rangkaian, laluan dan token |

## 10. Upgrade Hermes

**Prinsip:** program dalam image, data dalam volume. Upgrade = tukar image; volume tidak disentuh.

1. Build image `staffbot-hermes:<versi>` dengan versi Hermes yang ditetapkan. Baca changelog, terutamanya perubahan toolset dan config. Pastikan tool yang disekat tidak terbuka semula, dan tool baru yang berisiko dimatikan secara default.
2. Uji di **staging** dengan salinan data beberapa pelanggan ujian: chat, skill, memori, WhatsApp, Telegram.
3. **Snapshot** volume pelanggan sebelum upgrade.
4. **Canary:** ~5% pelanggan (akaun dalaman + pilot). Pantau 1–2 hari.
5. **Rolling:** berperingkat (cth 20 container satu masa). Container yang tidur akan menggunakan image baru apabila ia dibangunkan.
6. **Rollback:** tukar semula ke image lama. Simpan sekurang-kurangnya 2 versi lama. Pulihkan snapshot jika format data berubah.
7. Pakej Python yang pelanggan pasang sendiri: library popular dimasukkan dalam image; pakej custom disimpan dalam volume dan diuji semasa canary.

| Jenis | Kekerapan |
| :--- | :--- |
| Patch keselamatan (Hermes / OS) | Dalam 1–3 hari |
| Versi kecil Hermes | Bulanan |
| Versi besar Hermes | Selepas ≥ 1 minggu di staging |

Panel admin: pilih versi, pilih kumpulan (canary atau semua), kemudian **Update**. Status setiap container dipaparkan.

## 11. Backup dan pemulihan

| Data | Backup | Simpanan |
| :--- | :--- | :--- |
| Volume `HERMES_HOME` setiap pelanggan | Snapshot harian + sebelum upgrade | 14 hari |
| Postgres control plane | `pg_dump` harian, disulitkan, simpan di luar server | 14 hari |
| Ujian restore | Bulanan (satu pelanggan rawak + DB) | — |

## 12. Perkara belum diputuskan

| # | Perkara | Siapa |
| :--- | :--- | :--- |
| P1 | Angka pakej sebenar (harga, token, CPU/RAM/disk) | Remy |
| P2 | Angka pakej v1 (§7) dan mod console Starter | Remy |
| P3 | Tempoh idle sebelum tidur; sasaran masa bangun | Remy + ujian |
| P4 | Server khusus untuk node pelanggan (penyedia, saiz) | Remy, selepas ukur RAM sebenar satu Hermes |
| P5 | Versi Hermes yang dipin + **semak lesen** untuk hosting komersial | Teknikal |
| P6 | Mekanisme tool teras: plugin Hermes atau MCP server | Teknikal (uji) |
| P7 | Cara config asas read-only digabungkan dengan config pelanggan | Teknikal (uji) |
| P8 | Telegram: melalui router pusat (D15) atau gateway native Hermes per pelanggan | Teknikal |
| P9 | Tempoh simpanan data selepas langganan tamat (PDPA) | Remy |

## 13. Pelan peralihan (dari sistem sekarang)

Prinsip: **tiada downtime untuk pelanggan sedia ada**. Sistem lama berjalan selari sehingga pelanggan dipindahkan.

| Fasa | Kerja | Hasil |
| :--- | :--- | :--- |
| **0. Asas** | Deploy pembetulan keselamatan S-01–S-06; Alembic untuk migrasi DB; persekitaran staging; ukur RAM/CPU satu Hermes | Asas selamat + angka sebenar untuk P4 |
| **1. Image Hermes** | Hidupkan semula `hermes-core/`: pin versi, buang clone "latest", config asas read-only, toolset ikut pakej, tool teras StaffBot sebagai plugin/MCP | `staffbot-hermes:<versi>` |
| **2. LLM proxy** | Kecilkan `server-b/gateway` menjadi proxy: token per pelanggan, BYOK sebenar (betulkan B-03), model ikut pakej, kuota setiap pusingan, guardrail input + output | Semua LLM melalui satu titik |
| **3. Orchestrator** | Lanjutkan `docker_service.py`: gVisor, volume `HERMES_HOME`, firewall, tidur/bangun, upgrade canary/rolling, snapshot | Kitar hayat penuh |
| **4. Channel router** | Web chat, WhatsApp dan Telegram ke API Hermes pelanggan, dengan wake-on-message; betulkan aliran balasan (B-08, B-09) | Semua saluran berfungsi |
| **5. Dashboard** | Pelanggan: hidup/matikan katalog, skill custom, BYOK, penggunaan. Admin: versi, upgrade, status container | Layan diri |
| **6. Pilot** | 3–5 pelanggan pilot pada seni bina baharu | Pengesahan sebenar |
| **7. Migrasi** | Pindahkan pelanggan sedia ada secara berperingkat (memori `client_memory` diimport ke Hermes) | Semua pelanggan pada seni bina baharu |
| **8. Bersihkan** | Buang `hermes-gateway/`, `core-image/`, `sandbox/`, `hybrid-brain/`, `app_old/`, `.bak`, skrip lama; satu `docker-compose` | Repo kemas |

## 14. Risiko

| Risiko | Mitigasi |
| :--- | :--- |
| RAM tidak cukup apabila pelanggan bertambah | Scale-to-zero, had per pakej, reka bentuk berbilang node dari awal |
| Versi Hermes baru memecahkan sesuatu | Pin versi, staging, canary, rollback, snapshot |
| Pelanggan menyalahgunakan terminal (mining, spam, serangan keluar) | gVisor, had CPU, firewall keluar, blok port 25, pemantauan trafik, terma penggunaan |
| Kebocoran antara pelanggan | Satu container dan satu rangkaian per pelanggan, tiada kunci induk, token per pelanggan |
| Bergantung pada projek upstream (NousResearch) | Pin versi, simpan fork dalaman jika perlu, semak lesen |
