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

У регистратора `n8n-fitness.ru` (Beget):

| Тип | Имя   | Значение         | TTL |
|-----|-------|------------------|-----|
| A   | `@`   | `217.60.61.145`  | 300 |
| A   | `www` | `217.60.61.145`  | 300 |

Проверка с локальной машины:
```bash
dig +short n8n-fitness.ru
# должно вернуть 217.60.61.145
```

Не идти дальше, пока DNS не отвечает корректно через публичные резолверы.

## Шаг 2. Файлы на сервере

```bash
cd /root/n8n-fitness
git pull

cp .env.example .env
# заполнить N8N_ENCRYPTION_KEY: openssl rand -hex 32
```

## Шаг 3. Выпуск TLS-сертификата (standalone)

certbot работает в режиме standalone — он сам поднимает временный HTTP-сервер
на 80 порту. Поэтому общий nginx нужно остановить на ~30 секунд (`dev-rs-auto.store`
будет недоступен это время).

```bash
docker stop nginx

certbot certonly --standalone \
  -d n8n-fitness.ru -d www.n8n-fitness.ru \
  --email a.perevyazko@gmail.com --agree-tos --no-eff-email

docker start nginx
```

После успеха: `/etc/letsencrypt/live/n8n-fitness.ru/fullchain.pem` существует.

## Шаг 4. nginx vhost

В файле `/root/vacuum_remote/nginx/nginx.conf` внутрь `http { ... }` рядом с
существующими блоками для `dev-rs-auto.store` вставить server-блоки из
`nginx-n8n.conf` этого репо.

Применить:
```bash
docker exec nginx nginx -t
docker exec nginx nginx -s reload
```

## Шаг 5. Запуск n8n

```bash
cd /root/n8n-fitness
docker compose up -d
docker compose logs -f n8n
```

UI: `https://n8n-fitness.ru` — при первом заходе n8n попросит создать
owner-аккаунт.

## Авто-обновление сертификата

Сертификат живёт 90 дней, certbot автоматически обновляет за 30 дней до
истечения через `systemd` таймер `certbot.timer`. Но в standalone-режиме
обновление падает, если 80 порт занят nginx.

Решение — добавить hook'и для остановки/старта nginx во время renewal:

```bash
sudo mkdir -p /etc/letsencrypt/renewal-hooks/{pre,post}

sudo tee /etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh <<'EOF'
#!/bin/sh
docker stop nginx
EOF

sudo tee /etc/letsencrypt/renewal-hooks/post/start-nginx.sh <<'EOF'
#!/bin/sh
docker start nginx
EOF

sudo chmod +x /etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh \
              /etc/letsencrypt/renewal-hooks/post/start-nginx.sh
```

Проверить таймер:
```bash
systemctl list-timers | grep certbot
```

Симуляция renewal без реального запроса в LE:
```bash
sudo certbot renew --dry-run
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
