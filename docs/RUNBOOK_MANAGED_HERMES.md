# Runbook — Deploy Managed Hermes (Fasa 6–8)

> 23 Okt 2026. Untuk sesiapa yang ada akses root ke server (SSH melalui Tailscale).
> Kod sudah siap dan diuji (159 ujian, `api/tests/integration/`). **Semua langkah di bawah belum pernah dijalankan pada server sebenar**, jadi ikut urutan dan semak hasil setiap langkah.
> Peraturan: buat di **staging dahulu**. Production hanya selepas semua semakan staging lulus.

## 0. Ringkasan apa yang akan berjalan

| Servis | Dari | Peranan |
| :--- | :--- | :--- |
| `staffbot-api` | `api/` | Portal, admin, billing, channel router, orchestrator (melalui docker.sock) |
| `staffbot-llm-proxy` | `api/` (imej sama) | Satu-satunya laluan container pelanggan ke LLM + tool teras |
| `staffbot-hermes-worker` | `api/` (imej sama) | Tidurkan container idle, backup harian |
| `staffbot-hermes-<id>` | `hermes-core/` | Hermes Agent setiap pelanggan |
| `staffbot-baileys`, `staffbot-telegram` | `server-b/` | WhatsApp dan Telegram (sedia ada) |
| Lama: `staffbot-gateway`, `staffbot-<id>` | `server-b/` | Kekal berjalan sehingga semua pelanggan dipindahkan |

## 1. Prasyarat

- [ ] Pembetulan keselamatan S-01–S-06 sudah di-deploy (`docs/SECURITY_FINDINGS.md` §Deploy).
- [ ] Password `ubuntu` sudah ditukar, dan SSH guna key (S-24).
- [ ] **Server untuk container pelanggan.** Disyorkan server khusus (D13). Untuk staging dan pilot kecil, server OVH sedia ada boleh dipakai jika RAM cukup.
- [ ] Docker ≥ 24, dengan `iptables` (bukan nftables-only tanpa compat).
- [ ] Backup DB production diambil **sebelum** langkah 3.

## 2. Bina image Hermes pelanggan

```bash
cd /root/staffbot          # atau lokasi repo di server
docker pull nousresearch/hermes-agent:0.22.4
docker inspect --format '{{index .RepoDigests 0}}' nousresearch/hermes-agent:0.22.4   # catat digest
docker build --build-arg HERMES_IMAGE=nousresearch/hermes-agent:0.22.4@sha256:<digest> \
  -t staffbot-hermes:0.22.4-sb1 hermes-core/
```

Ujian asas image (tiada pelanggan lagi):
```bash
docker run --rm staffbot-hermes:0.22.4-sb1 ls /opt/hermes/plugins/staffbot /opt/staffbot/skills
```

## 3. Database

```bash
cd api
docker compose run --rm api alembic stamp 0001_baseline   # SEKALI SAHAJA pada DB sedia ada
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m scripts.seed_packages_v1          # dry run
docker compose run --rm api python -m scripts.seed_packages_v1 --apply  # tambah pakej yang belum ada
```

Semak: `\d packages` ada lajur baharu; `\d hermes_instances` wujud.

**Nota:** perintah `docker compose ... api` menggunakan servis `api` dalam `api/docker-compose.yml`. Sahkan dulu laluan `build:` yang betul di server (lihat `docs/SERVER_VERIFICATION.md` §3).

## 4. Sediakan host

```bash
sudo bash scripts/managed-hermes/setup-host.sh
sudo bash scripts/managed-hermes/setup-host.sh --check
sudo sh -c 'iptables-save > /etc/iptables/rules.v4'      # simpan peraturan
```

gVisor (disyorkan sebelum pelanggan sebenar):
```bash
# ikut https://gvisor.dev/docs/user_guide/install/ , kemudian:
sudo runsc install && sudo systemctl restart docker
docker run --rm --runtime=runsc staffbot-hermes:0.22.4-sb1 true && echo "gVisor OK"
```
Jika imej Hermes tidak boleh boot di bawah gVisor, biarkan `STAFFBOT_HERMES_RUNTIME` kosong dan rekod isu tersebut. Lapisan lain (firewall, cap_drop, rangkaian terasing) masih berkuat kuasa.

## 5. Konfigurasi `.env` (folder `api/`)

| Pembolehubah | Nilai |
| :--- | :--- |
| `STAFFBOT_LLM_PROXY_SECRET` | rawak 64 aksara (`openssl rand -hex 32`) |
| `LLM_PROXY_BIND` | `172.30.0.1` |
| `STAFFBOT_LLM_PROXY_PUBLIC_URL` | `http://172.30.0.1:8090` |
| `STAFFBOT_HERMES_IMAGE` | `staffbot-hermes:0.22.4-sb1` |
| `STAFFBOT_HERMES_RUNTIME` | `runsc` (atau kosong) |
| `STAFFBOT_MANAGED_HERMES_ENABLED` | `false` dahulu, `true` pada langkah 8 |
| `GATEWAY_AUTH_KEY` | sedia ada. Juga kunci yang dihantar oleh pengurus WhatsApp/Telegram |
| `MODERATION_API_KEY` | pilihan |

```bash
docker compose up -d --build api llm-proxy hermes-worker
curl -s http://172.30.0.1:8090/health          # {"status":"ok","service":"llm-proxy"}
```

Penyedia LLM: pastikan sekurang-kurangnya satu penyedia aktif dengan kunci, dan ia di-assign kepada setiap pakej (Admin → LLM Providers). Tanpa ini proxy akan memulangkan `no_provider`.

## 6. Pelanggan ujian dan semakan keselamatan

1. Cipta akaun ujian (pakej `professional`). Admin → **Hermes Agents**, atau:
   ```bash
   curl -X POST -H "Authorization: Bearer <admin JWT>" https://staffbot.my/api/v1/admin/hermes/<id>/provision
   ```
2. Semak container:
   ```bash
   docker ps --filter label=staffbot.type=hermes
   docker logs staffbot-hermes-<id> --tail 50
   docker exec staffbot-hermes-<id> cat /etc/hermes/config.yaml   # mesti read-only
   ```
3. **Ujian firewall dari dalam container pelanggan** (wajib lulus semua):
   ```bash
   C=staffbot-hermes-<id>
   docker exec $C curl -s -m 5 http://172.30.0.1:8090/health        # ✅ mesti berjaya
   docker exec $C curl -s -m 5 https://example.com -o /dev/null -w '%{http_code}\n'   # ✅ internet OK
   docker exec $C curl -s -m 5 http://172.30.0.1:8000/ || echo BLOCKED   # ✅ BLOCKED (API host)
   docker exec $C curl -s -m 5 http://169.254.169.254/ || echo BLOCKED  # ✅ BLOCKED
   docker exec $C curl -s -m 5 http://100.100.100.100/ || echo BLOCKED  # ✅ BLOCKED (Tailscale)
   docker exec $C sh -c 'nc -zw3 smtp.gmail.com 25 && echo OPEN || echo BLOCKED'   # ✅ BLOCKED
   ```
   Jika container lain wujud: port API container lain (`172.30.0.1:<port lain>`) mesti BLOCKED.
4. Ujian fungsi:
   - Portal pelanggan → **Hermes Agent** → chat: dapat jawapan.
   - Console: mod `shell` membuka bash; taip `hermes`.
   - Tanya ejen: "senaraikan tugasan saya" (tool `staffbot_list_tasks`).
   - Admin → Usage: token direkod (`token_usage_log`, endpoint `llm-proxy`).
5. **Ukur sumber** (untuk keputusan P4, saiz server):
   ```bash
   docker stats --no-stream --filter label=staffbot.type=hermes
   ```
   Rekod RAM ketika idle dan ketika sibuk, serta masa bangun dari tidur (sasaran < 10 s).

## 7. WhatsApp dan Telegram melalui router

Dalam `server-b/docker-compose.yml` (pengurus):
```
INCOMING_URL=http://staffbot-api:8000/api/v1/channels/incoming
```
Pengurus mesti boleh sampai ke `staffbot-api`, dan API mesti boleh sampai ke pengurus (`STAFFBOT_BAILEYS_MANAGER_URL`, `STAFFBOT_TELEGRAM_MANAGER_URL`). Sahkan kedua-dua berada dalam rangkaian Docker yang sama.

Pelanggan **tanpa** Hermes masih dihantar ke gateway lama secara automatik, jadi perubahan ini selamat dibuat sekali.

**Isu sedia ada yang perlu disemak:**
- URL webhook Telegram (`/api/telegram/webhook/{id}`) tidak sepadan dengan route pengurus (`/api/webhook/{id}`). Sahkan ada rewrite nginx.
- Token bot Telegram hilang bila pengurus restart (B-09).

## 8. Pilot (Fasa 6)

1. `STAFFBOT_MANAGED_HERMES_ENABLED=true`, kemudian `docker compose up -d api`. Pelanggan **baru** terus dapat Hermes.
2. Pindahkan 3–5 pelanggan pilot:
   ```bash
   docker compose run --rm api python -m scripts.migrate_to_managed_hermes --clients 12,15,18          # dry run
   docker compose run --rm api python -m scripts.migrate_to_managed_hermes --clients 12,15,18 --apply
   ```
3. Pantau 1–2 minggu:
   - status di Admin → Hermes Agents;
   - kos token dalam `token_usage_log`;
   - aduan pelanggan;
   - log `staffbot-llm-proxy`.

## 9. Migrasi semua pelanggan (Fasa 7)

```bash
docker compose run --rm api python -m scripts.migrate_to_managed_hermes --all            # dry run
docker compose run --rm api python -m scripts.migrate_to_managed_hermes --all --apply
```

## 10. Upgrade Hermes

1. Bina image baru (langkah 2) dengan tag baru, contohnya `staffbot-hermes:0.23.0-sb1`.
2. Admin → Hermes Agents → **Rollout**: Canary 5%, kemudian pantau, kemudian Semua.
3. Rollback: buat rollout dengan image lama. Setiap upgrade mengambil snapshot volume dahulu, dalam `/srv/staffbot/backups/<id>/`.

## 11. Bersihkan sistem lama (Fasa 8, selepas semua pelanggan dipindahkan)

- Hentikan dan buang container `staffbot-<id>` lama dan `staffbot-gateway`.
- Buang `server-b/gateway`, `server-b/core-image`, `sandbox/` dan `hermes-gateway/` dari repo.
- Buang `api/app/routers/chat.py` (laluan chat lama) dan halaman `customer/chat.html`, `customer/bots.html` jika tidak diperlukan lagi.
- Kemas kini `INCOMING_URL` sebagai default dalam kod pengurus.

## 12. Rollback keseluruhan

- `STAFFBOT_MANAGED_HERMES_ENABLED=false`: pelanggan baru kembali ke laluan lama.
- Kosongkan `INCOMING_URL` dalam compose pengurus: mesej kembali ke gateway lama.
- Data pelanggan dalam volume `staffbot-hermes-<id>` tidak terjejas.
- Alembic: `alembic downgrade 0001_baseline` membuang lajur dan jadual baharu. **Jangan** buat ini jika ada pelanggan yang sudah dipindahkan.
