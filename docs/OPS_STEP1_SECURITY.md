# Langkah 1: Keselamatan — arahan untuk dijalankan di server

> 23 Okt 2026. Dua bahagian:
> - **Bahagian A**: Remy buat sendiri. Ia melibatkan password dan key, jadi jangan beri pada bot.
> - **Bahagian B**: boleh di-paste kepada Mtt-mamat-bot. Ia berhenti di setiap titik semak dan tunggu "OK" sebelum meneruskan.
>
> **Deploy commit `154811c` sahaja**, bukan hujung branch. Hujung branch menambah lajur DB dan memerlukan migrasi Alembic (itu langkah 3, staging).

---

## Bahagian A — Remy buat sendiri (±10 minit)

Buat dari komputer awak, melalui Tailscale.

1. **Tukar password `ubuntu`:**
   ```bash
   ssh -p 333 ubuntu@100.83.136.71
   passwd                      # masukkan password baru yang kuat; simpan dalam password manager
   ```
2. **Pasang SSH key**, jika belum ada. Dari komputer awak:
   ```bash
   ssh-keygen -t ed25519 -C "remy-ovh"          # jika belum ada key
   ssh-copy-id -p 333 ubuntu@100.83.136.71
   ```
3. **Uji login dengan key dalam terminal BARU**, sambil sesi lama masih terbuka:
   ```bash
   ssh -p 333 -o PasswordAuthentication=no ubuntu@100.83.136.71 'echo KEY-OK'
   ```
   Teruskan ke langkah 4 **hanya jika** keluar `KEY-OK`.
4. **Matikan login password**, masih dalam sesi lama:
   ```bash
   sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
   sudo sshd -t && sudo systemctl reload ssh || sudo systemctl reload sshd
   ```
   Uji sekali lagi dengan terminal baru. Jika gagal, sesi lama masih boleh membetulkannya.
5. **Kemas kini akses bot.** Mtt-mamat-bot sekarang login dengan password. Beri bot SSH key sendiri (key berasingan, bukan key awak), atau biarkan bot hanya menjalankan arahan yang awak luluskan.
6. Padam mesej Telegram yang memaparkan password lama.

---

## Bahagian B — paste kepada Mtt-mamat-bot

> Salin semua di bawah garisan ini.

---

Tugas: deploy pembetulan keselamatan StaffBot (commit `154811c`) di server ini. Peraturan:
- Buat **satu fasa pada satu masa**. Di setiap **⛔ BERHENTI**, laporkan hasil dan tunggu saya balas "OK".
- **Jangan paparkan rahsia.** Untuk nilai dalam `.env`, tunjuk 4 aksara pertama sahaja diikuti `***`.
- Jika apa-apa tidak sama dengan yang dijangka, berhenti dan laporkan. Jangan cuba membetulkan sendiri.

### Fasa 1 — Semak keadaan (baca sahaja)
```bash
cd /root/staffbot 2>/dev/null || ls -d /home/*/staffbot /opt/staffbot 2>/dev/null
git remote -v; git branch --show-current; git log --oneline -1; git status --short | head -30
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' | grep -i staffbot
ls api/.env server-b/.env 2>/dev/null
grep -E '^(GATEWAY_AUTH_KEY|STAFFBOT_SERVER_B_API_KEY|STAFFBOT_GATEWAY_API_KEY|HERMES_API_KEY|MODERATION_API_KEY)=' api/.env | sed -E 's/=(.{4}).*/=\1***/'
docker exec staffbot-gateway env | grep -E '^(AUTH_KEY|SERVER_B_API_KEY)=' | sed -E 's/=(.{4}).*/=\1***/'
docker inspect staffbot-api --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
docker inspect staffbot-gateway --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}} {{.Config.Image}}'
```
Laporkan:
- lokasi repo, branch, commit dan sama ada `git status` kosong;
- container staffbot yang berjalan;
- 4 aksara pertama setiap kunci;
- folder compose bagi `staffbot-api` dan `staffbot-gateway`.

**Dijangka:** commit `06d7149`, dan `git status` kosong. Jika ada fail yang diubah atau tidak dijejak, senaraikan semuanya.
⛔ BERHENTI

### Fasa 2 — Backup
```bash
TS=$(date +%Y%m%d-%H%M)
sudo mkdir -p /root/backups
docker exec staffbot-db pg_dump -U staffbot -d staffbot_db | gzip | sudo tee /root/backups/staffbot_db-$TS.sql.gz >/dev/null
ls -la /root/backups/staffbot_db-$TS.sql.gz
sudo cp api/.env /root/backups/api.env-$TS
git rev-parse HEAD | sudo tee /root/backups/git-head-$TS
```
Laporkan saiz fail backup (mesti lebih besar dari 0).
⛔ BERHENTI

### Fasa 3 — Ambil kod pembetulan
```bash
git fetch origin claude/staffbot-my-review-i3w7be
git checkout -b security-fix-154811c 154811c
git log --oneline -1          # mesti: 154811c security: fix 6 critical findings
git diff --stat 06d7149 154811c -- api server-b
```
⛔ BERHENTI

### Fasa 4 — Kemas kini `.env` (folder `api/`)
Tetapkan nilai-nilai ini dalam `api/.env`. **Jangan paparkan nilai.**
1. **Kunci gateway baru.** Kunci lama sudah berada di dalam setiap container klien, jadi ia mesti ditukar:
   ```bash
   NEW=$(openssl rand -hex 32)
   sed -i "s/^GATEWAY_AUTH_KEY=.*/GATEWAY_AUTH_KEY=$NEW/" api/.env
   sed -i "s/^STAFFBOT_SERVER_B_API_KEY=.*/STAFFBOT_SERVER_B_API_KEY=$NEW/" api/.env
   ```
   `GATEWAY_AUTH_KEY` dan `STAFFBOT_SERVER_B_API_KEY` **mesti sama**.
2. **`STAFFBOT_GATEWAY_API_KEY`:**
   - jika ada container Hermes gateway (`hermes-gateway`) yang menggunakan `GATEWAY_API_KEY`, nilainya mesti sama dengan nilai di situ;
   - jika tiada, jana nilai rawak baru: `openssl rand -hex 32`.
3. Jika pengurus WhatsApp/Telegram (`staffbot-baileys`, `staffbot-telegram`) mempunyai `.env` atau compose sendiri, tukar `GATEWAY_AUTH_KEY` di sana kepada nilai **sama** dengan langkah 1.
4. Semak tanpa paparkan nilai:
   ```bash
   grep -E '^(GATEWAY_AUTH_KEY|STAFFBOT_SERVER_B_API_KEY|STAFFBOT_GATEWAY_API_KEY)=' api/.env | sed -E 's/=(.{4}).*/=\1***/'
   ```

⛔ BERHENTI

### Fasa 5 — Bina semula dan restart
Gunakan folder compose yang dilaporkan dalam Fasa 1.
```bash
docker compose -f <folder-api>/docker-compose.yml build api
docker build -t staffbot-gateway:latest server-b/gateway/
docker compose -f <folder-api>/docker-compose.yml up -d api gateway
# pengurus WhatsApp/Telegram, supaya mereka menggunakan kunci baru:
docker restart staffbot-baileys staffbot-telegram
sleep 10; docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -i staffbot
docker logs staffbot-api --tail 30; docker logs staffbot-gateway --tail 30
```
⛔ BERHENTI

### Fasa 6 — Uji pembetulan
```bash
B=http://127.0.0.1:8000/api/v1
# S-01: endpoint token tanpa kunci mesti ditolak (401 atau 500 "not configured"), BUKAN 200
curl -s -o /dev/null -w 'S-01 tanpa kunci: %{http_code}\n' -X PUT $B/subscriptions/1/tokens -H 'Content-Type: application/json' -d '{"managed_token_used":0}'
# S-03: kunci default lama mesti ditolak (401)
curl -s -o /dev/null -w 'S-03 kunci lama: %{http_code}\n' $B/tasks/list -H 'X-Internal-Key: hermes-gateway-key-2024-secure' -H 'X-Client-ID: 1'
# Kesihatan
curl -s $B/health; echo
curl -s -o /dev/null -w 'gateway health: %{http_code}\n' http://127.0.0.1:8080/health
```
**Dijangka:** S-01 → `401`, S-03 → `401`, health → `ok`, gateway → `200`.
Uji juga: login ke portal pelanggan dan hantar satu mesej chat. Ia mesti berjaya.
⛔ BERHENTI

### Fasa 7 — Cipta semula container klien lama (untuk S-05)
Container klien lama masih memegang kunci gateway lama. Cipta semula satu demi satu:
```bash
docker ps -a --filter label=staffbot.type=client --format '{{.Names}} {{.Label "staffbot.client_id"}}'
```
Untuk **setiap** container (mulakan dengan satu, semak, kemudian teruskan):
```bash
docker rm -f staffbot-<id>
curl -s -X POST -H "Authorization: Bearer <JWT admin>" http://127.0.0.1:8000/api/v1/admin/users/<client_id>/deploy
docker exec staffbot-<id> printenv GATEWAY_AUTH_KEY | cut -c1-4    # mesti BUKAN 4 aksara kunci lama
```
Data klien kekal kerana ia berada di `/root/staffbot/containers/staffbot-<id>` (di host).
⛔ BERHENTI. Laporkan senarai container yang sudah dicipta semula.

---

## Jika ada yang rosak (rollback)
```bash
git checkout <commit dari /root/backups/git-head-TS>
sudo cp /root/backups/api.env-TS api/.env
docker compose -f <folder-api>/docker-compose.yml build api && docker compose -f <folder-api>/docker-compose.yml up -d api gateway
docker restart staffbot-baileys staffbot-telegram
```
Pembetulan ini tidak mengubah DB, jadi rollback tidak memerlukan pemulihan DB.
