# n8n-fitness

Self-hosted n8n под персонального фитнес-ассистента (Telegram + GPT + Google Sheets).

Домен: **n8n-fitness.ru** (HTTPS через Caddy + Let's Encrypt).

## Подготовка домена

1. У регистратора прописать A-record `n8n-fitness.ru` → IP сервера.
2. Дождаться, пока `dig +short n8n-fitness.ru` вернёт нужный IP.

## Деплой на сервер

```bash
git clone <repo> n8n-fitness && cd n8n-fitness

cp .env.example .env
# заполнить N8N_ENCRYPTION_KEY: openssl rand -hex 32

docker compose up -d
docker compose logs -f
```

UI: `https://n8n-fitness.ru` — при первом заходе n8n попросит создать owner-аккаунт.

Первый запрос Caddy выпустит TLS-сертификат через Let's Encrypt (нужны открытые
80 и 443 порты + корректный A-record).

## Firewall

```bash
ufw allow 80/tcp
ufw allow 443/tcp
# порт 5678 наружу НЕ открывать — n8n доступен только через Caddy
```

## Локальный запуск

Локально через https-домен не поднять без подмены DNS. Для разработки можно
временно вернуть прямой проброс `5678:5678` на сервисе n8n и `N8N_PROTOCOL=http`,
но в репо этот режим не держим.

## Бэкап

```bash
docker run --rm -v n8n-fitness_n8n_data:/data -v $PWD:/backup alpine \
  tar czf /backup/n8n-backup-$(date +%F).tar.gz -C /data .
```

В томе `n8n_data` лежат credentials и workflow'ы. `N8N_ENCRYPTION_KEY` из `.env`
бэкапить отдельно — без него восстановление credentials невозможно.

## Обновление

```bash
docker compose pull
docker compose up -d
```
