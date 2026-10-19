# PRD — StaffBot.my (keadaan sebenar, "as-built")

> Versi dokumen: 2.0 (19 Okt 2026). Menggantikan PRD v1 yang ditulis sebelum pembangunan.
> Dokumen ini menerangkan **apa yang sistem lakukan sekarang**, berdasarkan kod. Ciri yang hanya dirancang ditanda dengan jelas.
> Status: ✅ berfungsi dalam kod · ⚠️ separa / ada bug · ❌ belum ada · **[SAHKAN-SERVER]** perlu disemak di server.

## 1. Gambaran produk

**StaffBot.my** ialah platform "Digital Employee as a Service" untuk PKS Malaysia, keluaran Marz Technology and Trading. Pelanggan melanggan pakej, kemudian mendapat "AI Staff" (bot) yang boleh:

- berbual dengan pelanggan atau pemilik melalui **dashboard web** (WhatsApp dan Telegram dirancang, tetapi aliran balasan AI belum lengkap, lihat §4);
- mengingati fakta syarikat (memori);
- melaksanakan tindakan melalui tool: panggil API luar (webhook), carian web, hantar email, cipta tugasan.

### Masalah yang diselesaikan
PKS tidak mampu menggaji staf tambahan untuk khidmat pelanggan dan kerja rutin. StaffBot menyediakan ejen AI yang bekerja 24/7 dengan kos langganan bulanan.

## 2. Pengguna

| Peranan | Bagaimana dikenal pasti dalam sistem | Boleh buat |
| :--- | :--- | :--- |
| **Admin platform (Marz)** | Akaun yang email = `STAFFBOT_ADMIN_EMAIL` | Urus pelanggan, pakej, penyedia LLM, subdomain, top-up, affiliate, polisi skill/tool, lihat penggunaan |
| **Pelanggan (pemilik syarikat)** | Satu baris dalam jadual `clients` | Daftar, bayar, cipta bot, chat, tugasan, BYOK, saluran notifikasi, affiliate |
| Staf syarikat pelanggan | ❌ **Tiada konsep ini** | — |

> Penting: "Staff" dalam StaffBot bermaksud **bot AI**, bukan pengguna manusia. Satu syarikat = satu login.

## 3. Pakej dan model bisnes

| Pakej (seed) | Harga bulanan | Tahunan (paparan sahaja) | Token terurus |
| :--- | :--- | :--- | :--- |
| starter | RM49 | RM499 | 100k |
| professional | RM149 | RM1,499 | 500k |
| enterprise | RM499 | RM4,999 | 2M |

**[SAHKAN-SERVER]** Harga sebenar disimpan dalam jadual `packages` dan boleh diubah oleh admin.

**Pembayaran**
- Stripe Checkout dalam MYR (kad + FPX), bayaran **sekali sahaja** (`mode=payment`).
- ❌ Tiada langganan berulang atau pembaharuan automatik. ❌ Tiada logik percubaan percuma, walaupun laman utama menyebut "7 hari percuma".

**Lain-lain**
- **Top-up token**: pakej top-up dibeli melalui Stripe untuk menambah kuota.
- **BYOK**: pelanggan boleh simpan API key sendiri. ⚠️ Kunci yang disimpan **tidak digunakan** semasa chat. Lihat SRS FR-CHAT-3.
- **Affiliate**: kod rujukan, klik, penukaran, permintaan bayaran. ⚠️ Komisen tidak pernah dikira secara automatik.

## 4. Ciri utama dan status

| # | Ciri | Status | Nota |
| :--- | :--- | :--- | :--- |
| P1 | Pendaftaran dan login pelanggan (JWT) | ✅ | Satu akaun bagi setiap syarikat |
| P2 | Rizab subdomain semasa daftar | ✅ | `namasyarikat.staffbot.my` |
| P3 | Bayaran pakej (Stripe) | ✅ | Bayaran sekali; kuota tidak di-reset bila beli semula |
| P4 | Deploy container per klien | ⚠️ | Container dicipta, tetapi **tiada ejen AI di dalamnya**. Rekod DNS Cloudflare rosak (diberi nama domain, bukan IP) |
| P5 | Cipta beberapa "AI Staff" (bot) | ⚠️ | Had ikut `bot_limit` pakej. Semua bot berkongsi satu container; padam satu bot akan memadam container untuk semua |
| P6 | Chat web dengan AI | ✅ | Melalui gateway berkongsi, tanpa streaming, tanpa sejarah perbualan dihantar ke LLM |
| P7 | Lampiran dalam chat (PDF, DOCX, imej) | ✅ | Teks diekstrak dan dihantar bersama mesej; imej melalui model vision |
| P8 | Memori syarikat (Central Brain v2) | ⚠️ | Simpan dan cari berasaskan teks. Carian vektor tidak berfungsi. Endpoint upload dokumen ke memori rosak (modul hilang) **[SAHKAN-SERVER]** |
| P9 | Auto-klasifikasi perbualan (fakta/tugasan/keutamaan) | ✅ | Panggilan LLM tambahan selepas setiap chat |
| P10 | Tool ejen: `call_webhook`, `web_search`, `send_email`, `set_smtp_config`, memori, masa | ✅ | Ada had kadar per klien |
| P11 | Tool `create_document` (Word/PPT/Excel) | ❌ | Hanya dalam pelan (`ENHANCEMENT_PLAN.md` Fasa 5) |
| P12 | Tugasan (task) | ✅ | CRUD melalui web; ejen boleh cipta tugasan |
| P13 | WhatsApp (Baileys) | ⚠️ | Sesi QR dan hantar mesej ada. **Balasan AI automatik untuk mesej masuk tidak lengkap dalam kod** **[SAHKAN-SERVER]** |
| P14 | Telegram | ⚠️ | Sama seperti WhatsApp; token bot hilang bila servis restart |
| P15 | Moderasi kandungan 3 lapis | ✅ | Regex, klasifikasi AI, dan jejak perbualan |
| P16 | Audit trail | ✅ | Jadual `audit_trail` |
| P17 | Kuota token dan penggunaan | ✅ | Ditolak selepas setiap chat. Pusingan tool tidak dikira sepenuhnya |
| P18 | Panel admin | ✅ | Ada beberapa halaman yang memanggil endpoint yang tidak wujud |
| P19 | Polisi skill/tool (788 skill katalog) | ⚠️ | Skill hanya disenaraikan sebagai teks dalam prompt; tiada kod skill dijalankan |
| P20 | OCR (Tesseract BM) | ❌ | Library dipasang dalam image, tetapi tiada kod yang memanggilnya |
| P21 | Agent Office (visualisasi piksel) | ✅ | Servis berasingan pada port 3334 **[SAHKAN-SERVER]** |
| P22 | Mobile app | ❌ | Hanya web responsif |
| P23 | Suara (STT/TTS/wake word) | ❌ | Tiada kod |
| P24 | Akaun staf, cawangan, jabatan, RBAC, kelulusan | ❌ | Tiada |

## 5. Perjalanan pengguna sebenar

1. **Daftar.** Pelanggan isi borang di laman utama (nama, email, syarikat, subdomain, telefon, pakej, password). Akaun dicipta dengan status `pending`.
2. **Bayar.** Pelanggan pilih pakej di halaman billing, kemudian Stripe Checkout. Webhook Stripe mengaktifkan langganan, menetapkan kuota token, dan deploy container.
   - Admin juga boleh "force deploy" tanpa bayaran.
3. **Setup.** Pelanggan masukkan BYOK (pilihan), token Telegram dan nombor WhatsApp.
4. **Cipta bot.** Halaman "My AI Staff".
5. **Chat.** Halaman chat:
   1. Mesej dihantar ke API.
   2. Mesej melalui moderasi.
   3. API mencari memori.
   4. Gateway memanggil LLM dengan tool.
   5. Jawapan dipaparkan dan token ditolak.
6. **Tugasan dan memori.** Ejen boleh mencipta tugasan dan menyimpan fakta secara automatik.

## 6. Bukan dalam skop sekarang

Mobile app, suara, akaun berbilang pengguna dalam satu syarikat, kelulusan, RAG dokumen sebenar dengan embedding, langganan berulang, dan ERP.
→ Lihat `GAP_ANALYSIS_HERMES_HUB.md` untuk cadangan menambah semua ini.

## 7. Sasaran bukan fungsian (daripada PRD v1, belum diukur)

| Perkara | Sasaran |
| :--- | :--- |
| Respons AI | < 5 s |
| Carian memori | < 500 ms |
| Uptime | 99.9% |

Tiada pemantauan dalam repo untuk mengukur sasaran ini.
