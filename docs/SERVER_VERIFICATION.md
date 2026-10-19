# Senarai Semakan Server (BACA SAHAJA)

> Untuk mengesahkan perkara bertanda **[SAHKAN-SERVER]** dalam dokumentasi.
> Jalankan di server OVH melalui Tailscale.

**Peraturan**
- **Jangan** ubah, restart atau deploy apa-apa.
- **Tutup (mask) semua rahsia** sebelum berkongsi output.

## 1. Container dan image
```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' | grep -i staffbot
docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}' | grep -iE 'staffbot|hermes'
docker inspect staffbot-gateway --format '{{.Config.Image}} {{json .Config.Cmd}} {{json .Config.Entrypoint}}'
docker inspect staffbot-embeddings --format '{{.Config.Image}} {{json .Config.Cmd}}'
docker ps --filter label=staffbot.type=client --format '{{.Names}}' | wc -l   # bilangan container klien
```

## 2. Kod mana yang berjalan dalam gateway
```bash
docker exec staffbot-gateway ls /app
docker exec staffbot-gateway sh -c 'grep -c "v1/chat/completions" /app/*.py'
# Jika ada main.py dengan ReAct, ini server-b/gateway; jika ada gateway_api.py dan hermes, ini hermes-gateway
```

## 3. Lokasi kod dan git di server
```bash
ls -d /root/staffbot /home/*/staffbot /opt/staffbot 2>/dev/null
cd <lokasi> && git remote -v && git branch --show-current && git log --oneline -1 && git status --short | head -30
```
`git status` menunjukkan sama ada ada fail yang tidak di-commit, contohnya `memory_service.py`.

## 4. Modul memori yang hilang
```bash
docker exec staffbot-api ls /app/app/services/ | grep -i memory
```

## 5. Skema DB (struktur sahaja, tiada data)
```bash
docker exec staffbot-db psql -U staffbot -d staffbot_db -c '\dt'
docker exec staffbot-db psql -U staffbot -d staffbot_db -c '\d client_memory'
docker exec staffbot-db psql -U staffbot -d staffbot_db -c '\d packages'
docker exec staffbot-db psql -U staffbot -d staffbot_db -c 'SELECT count(*) FROM clients'
docker exec staffbot-db psql -U staffbot -d staffbot_db -c 'SELECT count(*), count(embedding) FROM client_memory'
docker exec staffbot-memory-db psql -U staffbot -d staffbot_memory -c '\dt'
```

## 6. Nginx dan routing subdomain
```bash
ls /etc/nginx/conf.d/
grep -l staffbot /etc/nginx/conf.d/*
cat /etc/nginx/ssl/subdomain_ports.map | wc -l
crontab -l | grep -i nginx
```

## 7. Env var (nama sahaja, tanpa nilai)
```bash
docker exec staffbot-api env | cut -d= -f1 | sort
docker exec staffbot-gateway env | cut -d= -f1 | sort
```
Semak sama ada `GATEWAY_API_KEY` atau `STAFFBOT_GATEWAY_API_KEY` wujud (berkaitan isu S-03).

## 8. Saluran WhatsApp
- Hantar satu mesej ujian ke nombor WhatsApp bot klien ujian, kemudian tengok sama ada AI membalas.
- Semak log berikut:
```bash
docker logs staffbot-baileys --tail 50
docker logs staffbot-gateway --tail 100 | grep -i incoming
```

## 9. Sumber server
```bash
nproc; free -h; df -h /; uptime
```

## 10. Backup
```bash
crontab -l; ls /etc/cron.d/; ls -la /root/backups 2>/dev/null
```

Hantar output (dengan rahsia ditutup), dan dokumen akan dikemas kini daripada [SAHKAN-SERVER] kepada fakta yang disahkan.
