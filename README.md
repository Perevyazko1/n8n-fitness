# n8n-fitness

Self-hosted n8n под персонального фитнес-ассистента (Telegram + GPT + Google Sheets).

## Деплой на сервер

```bash
git clone <repo> n8n-fitness && cd n8n-fitness

cp .env.example .env
# заполнить: N8N_HOST=<IP сервера>, WEBHOOK_URL=http://<IP>:5678/
# сгенерировать ключ: openssl rand -hex 32  → в N8N_ENCRYPTION_KEY

docker compose up -d
docker compose logs -f n8n
```

UI: `http://<IP>:5678` — при первом заходе n8n попросит создать owner-аккаунт.

Firewall:
```bash
ufw allow 5678/tcp
```

## Локальный запуск

В `.env`: `N8N_HOST=localhost`, `WEBHOOK_URL=http://localhost:5678/`.

## TODO до боевого использования

- [ ] Купить домен, навесить A-record на IP сервера
- [ ] Добавить Caddy/Traefik с Let's Encrypt → HTTPS обязателен для:
  - Telegram webhook
  - Google OAuth (Sheets/Drive)
- [ ] Поменять `WEBHOOK_URL` и `N8N_PROTOCOL=https`
- [ ] Бэкап тома `n8n_data` (там credentials и workflow'ы)

## Бэкап

```bash
docker run --rm -v n8n-fitness_n8n_data:/data -v $PWD:/backup alpine \
  tar czf /backup/n8n-backup-$(date +%F).tar.gz -C /data .
```
