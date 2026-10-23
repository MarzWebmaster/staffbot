# Dokumentasi StaffBot.my — Indeks

> Dikemas kini: 19 Okt 2026
> Sumber: kod dalam repo ini (branch `claude/staffbot-my-review-i3w7be`). Kod ini ialah kod yang di-deploy ke server production.
> **Kod di server belum dibandingkan secara langsung.** Perkara yang perlu disahkan di server ditanda **[SAHKAN-SERVER]** dan disenaraikan dalam `SERVER_VERIFICATION.md`.

| Dokumen | Isi | Untuk siapa |
| :--- | :--- | :--- |
| [PRD.md](PRD.md) | Apa produk ini, untuk siapa, ciri yang **benar-benar wujud** sekarang | Pemilik, pengurus, sales |
| [SRS.md](SRS.md) | Keperluan fungsian dan bukan fungsian, dengan status sebenar setiap satu (✅ / ⚠️ / ❌) | Developer, QA |
| [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) | **Seni bina sasaran**: managed Hermes per pelanggan, keputusan D1–D18, pakej, portal, upgrade, pelan peralihan, **status pelaksanaan** | Pemilik, developer |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Komponen, container, aliran chat, aliran WhatsApp/Telegram, provisioning | Developer, DevOps |
| [DATABASE.md](DATABASE.md) | Semua jadual dan lajur, penyulitan, isu skema | Developer |
| [API.md](API.md) | Senarai penuh endpoint dan jenis auth | Developer, mobile/web dev |
| [SECURITY_FINDINGS.md](SECURITY_FINDINGS.md) | Isu keselamatan dan bug yang ditemui, mengikut keutamaan | Pemilik, developer |
| [GAP_ANALYSIS_HERMES_HUB.md](GAP_ANALYSIS_HERMES_HUB.md) | Perbandingan StaffBot sedia ada dengan PRD v2 (Enterprise Hermes Hub) | Pemilik |
| [HERMES_VOICE_PROJECT_BRIEF.md](HERMES_VOICE_PROJECT_BRIEF.md) | Brief projek Enterprise Hermes Hub (PRD v2) daripada Remy | Rujukan |
| [OPS_STEP1_SECURITY.md](OPS_STEP1_SECURITY.md) | **Langkah 1**: tukar password/SSH key + deploy pembetulan S-01–S-06 (untuk bot, berfasa) | Remy, DevOps |
| [RUNBOOK_MANAGED_HERMES.md](RUNBOOK_MANAGED_HERMES.md) | **Langkah deploy** managed Hermes: image, DB, firewall, pilot, migrasi, upgrade, rollback | DevOps |
| [../api/tests/integration/](../api/tests/integration/README.md) | 162 ujian integrasi (`run_all.sh`) | Developer |
| [SERVER_VERIFICATION.md](SERVER_VERIFICATION.md) | Arahan baca sahaja untuk mengesahkan dokumen ini di server | DevOps |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Cara deploy (lama, perlu disahkan semula di OVH) | DevOps |

## Ringkasan 30 saat

> Ini keadaan **production sekarang**. Seni bina baharu (Hermes Agent sendiri untuk setiap pelanggan) sudah dibina dan diuji di branch ini, tetapi belum di-deploy. Lihat `TARGET_ARCHITECTURE.md` §0 dan `RUNBOOK_MANAGED_HERMES.md`.

- StaffBot.my ialah SaaS "AI Employee" berbilang klien. **Satu akaun = satu syarikat (tenant)**. Tiada akaun staf di dalam syarikat.
- Semua panggilan AI melalui **satu gateway berkongsi** (`staffbot-gateway`, FastAPI tersuai) yang memanggil penyedia LLM serasi OpenAI (DeepSeek, OpenRouter dan lain-lain). Container per klien (`staffbot-core`) memang dicipta, tetapi **tidak mengandungi ejen AI**.
- Ejen ada tool: carian memori, simpan memori, `call_webhook`, `web_search`, `send_email`, dan tugasan (task).
- Memori ("Central Brain v2") menggunakan carian teks (ILIKE + full-text + terkini). **Carian vektor tidak berfungsi** dalam kod sekarang, kerana tiada kod yang menjana embedding.
- Web: dashboard pelanggan dan admin (HTML + Tailwind + vanilla JS). **Tiada mobile app, tiada suara.**
- Ada beberapa isu keselamatan **kritikal**. Lihat `SECURITY_FINDINGS.md`.
