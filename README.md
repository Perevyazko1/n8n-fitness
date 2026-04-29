# n8n-fitness

Self-hosted n8n под персонального фитнес-ассистента (Telegram + GPT + Google Sheets).

Домен: **n8n-fitness.ru**.
TLS и публичные 80/443 обслуживает уже существующий на сервере контейнер
`nginx` (host network) — он же фронтит другой проект. Сюда n8n подключается как
ещё один vhost; наш compose поднимает только n8n, привязанный к `127.0.0.1:5678`.

## Архитектура

```
Internet → :443 nginx (host net) ──┬─ dev-rs-auto.store → 127.0.0.1:8000 (django)
                                   └─ n8n-fitness.ru   → 127.0.0.1:5678 (n8n, наш compose)
```

## Шаг 1. DNS

У регистратора `n8n-fitness.ru`:

| Тип | Имя | Значение         | TTL |
|-----|-----|------------------|-----|
| A   | `@` | `217.60.61.145`  | 300 |
| A   | `www` | `217.60.61.145` | 300 |

Проверка:
```bash
dig +short n8n-fitness.ru
# должно вернуть 217.60.61.145
```

Не идти дальше, пока DNS не отвечает корректно.

## Шаг 2. Файлы на сервере

```bash
cd /root/n8n-fitness
git pull   # если уже клонировано, иначе git clone

cp .env.example .env
# заполнить N8N_ENCRYPTION_KEY: openssl rand -hex 32
```

## Шаг 3. Временный HTTP-vhost для ACME-challenge

Чтобы certbot смог получить сертификат, в существующем nginx должен быть
server-блок на 80 порту с `location /.well-known/acme-challenge/`. В файле
`nginx-n8n.conf` (этот репо) такой блок уже есть.

1. Открыть на сервере `/root/vacuum_remote/nginx/nginx.conf`.
2. **Внутрь** существующего `http { ... }` вставить server-блоки из
   `nginx-n8n.conf` этого репо. Пока **временно** закомментировать оба
   `listen 443 ssl` блока — сертификата ещё нет, nginx с ними не стартует.
3. Применить:
   ```bash
   docker exec nginx nginx -t
   docker exec nginx nginx -s reload
   ```

## Шаг 4. Выпуск сертификата

```bash
certbot certonly --webroot -w /var/www/certbot \
  -d n8n-fitness.ru -d www.n8n-fitness.ru \
  --email a.perevyazko@gmail.com --agree-tos --no-eff-email
```

После успеха: `/etc/letsencrypt/live/n8n-fitness.ru/fullchain.pem` существует.

## Шаг 5. Включить HTTPS-vhost и поднять n8n

1. В `/root/vacuum_remote/nginx/nginx.conf` раскомментировать оба `443`-блока.
2. Релоад nginx:
   ```bash
   docker exec nginx nginx -t
   docker exec nginx nginx -s reload
   ```
3. Поднять n8n:
   ```bash
   cd /root/n8n-fitness
   docker compose up -d
   docker compose logs -f n8n
   ```

UI: `https://n8n-fitness.ru` — при первом заходе n8n попросит создать
owner-аккаунт.

## Авто-обновление сертификата

certbot уже стоит в системе (`/usr/bin/certbot`). Проверить таймер:
```bash
systemctl list-timers | grep certbot
```
После рефреша nginx нужно перезагрузить — добавить deploy-hook:
```bash
echo '#!/bin/sh
docker exec nginx nginx -s reload' \
  | sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

## Бэкап

```bash
docker run --rm -v n8n-fitness_n8n_data:/data -v $PWD:/backup alpine \
  tar czf /backup/n8n-backup-$(date +%F).tar.gz -C /data .
```

В томе `n8n_data` лежат credentials и workflow'ы. `N8N_ENCRYPTION_KEY` из `.env`
бэкапить отдельно — без него восстановление credentials невозможно.

## Обновление n8n

```bash
cd /root/n8n-fitness
docker compose pull
docker compose up -d
```
