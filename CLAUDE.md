# CLAUDE.md

Заметки для Claude Code по этому репозиторию.

## Что это

Репозиторий для self-hosted деплоя **n8n** через Docker Compose. Используется как
персональный фитнес-ассистент: Telegram → n8n → OpenAI → Google Sheets.

В репо лежит **только инфраструктура** (compose, env-шаблон, README). Сами
workflow'ы конфигурируются внутри UI n8n и (опционально) экспортируются JSON'ом.

## Структура

- `docker-compose.yml` — один сервис `n8n`, привязан к `127.0.0.1:5678`
- `nginx-n8n.conf` — vhost для встраивания в существующий nginx на сервере
  (мы НЕ управляем им из этого compose)
- `.env.example` — шаблон, реальный `.env` в git не коммитится
- `README.md` — инструкция по деплою (DNS → nginx vhost → certbot → up -d)
- `.gitignore` — `.env`, `.idea/`, `data/`, `.DS_Store`

Никаких `package.json`, `src/`, языков программирования здесь нет и не должно быть.

## Правила работы

**Разделение ролей:**

- **Локальная машина:** Claude вносит изменения в файлы репо. Пользователь сам
  делает `git add` / `git commit` / `git push`. Никогда не запускай пишущие
  git-команды (commit, push, tag, reset, rebase) — только чтение
  (`git status`, `git diff`, `git log`).
- **VPS (сервер):** Claude работает **только в read-only**. Разрешено:
  `docker compose ps/logs`, `cat`, `ls`, чтение конфигов, диагностика.
  **Запрещено:** редактировать файлы на сервере, делать `docker compose up/down`
  самостоятельно без явной просьбы, править env, перезапускать сервисы.
  Любая правка идёт через цикл: правка локально → пользователь коммитит и
  пушит → пользователь делает `git pull` и применяет на сервере.

**Прочее:**

- Не плоди файлы без запроса (особенно `*.md`, доки, планы).
- Не возвращай в репо удалённое: TS-скаффолдинг (`src/`, `tsconfig.json`,
  `package.json`) был намеренно вычищен.
- Секреты и IP — только через `.env`, не хардкодить в `docker-compose.yml`.

## Текущее состояние инфраструктуры

- Сервер: `217.60.61.145`, Ubuntu 24.04, Docker 29.3.0, Compose v5.1.0.
- Домен: `n8n-fitness.ru`. A-records `@` и `www` → `217.60.61.145`.
- На сервере уже работает host-network контейнер `nginx`
  (конфиг `/root/vacuum_remote/nginx/nginx.conf`), фронтит `dev-rs-auto.store`
  для django:8000. Он же фронтит наш домен — добавляем vhost туда.
- TLS: certbot 2.9.0 на хосте, тома `/etc/letsencrypt` уже монтируются в
  контейнер nginx. Сертификат на `n8n-fitness.ru` выпускается через
  `certbot certonly --webroot -w /var/www/certbot`.
- n8n биндится **только** на `127.0.0.1:5678`. Наружу не торчит.
- Таймзона: `Europe/Moscow`.

## Чужие сервисы на сервере (не трогать)

- `nginx` (host net) — общий фронт, конфиг в репо `/root/vacuum_remote/`
- `django-back` (8000), `vacuum_remote` — другой проект
- `3x-ui` (2053), `amnezia-wg` (51820/51821), `mtproto-proxy` (993)
- Менять их конфиги нельзя без явной просьбы; правка `nginx.conf` — только
  добавление наших vhost-блоков из `nginx-n8n.conf`.

## Версии и совместимость n8n

- Образ: `n8nio/n8n:latest`.
- `N8N_BASIC_AUTH_*` **не использовать** — удалены в n8n 1.0+. Авторизация
  через owner-аккаунт, который n8n создаёт при первом заходе в UI.
- `version:` в compose не указывать — Compose v2 ругается, поле игнорируется.
- `N8N_ENCRYPTION_KEY` обязателен и должен быть стабильным: при его потере
  все сохранённые credentials становятся нечитаемы.

## Полезные команды

```bash
docker compose config -q          # валидация compose
docker compose up -d              # старт
docker compose logs -f n8n        # логи
docker compose ps                 # статус
docker compose pull && docker compose up -d   # обновление образа
```

Бэкап тома:

```bash
docker run --rm -v n8n-fitness_n8n_data:/data -v $PWD:/backup alpine \
  tar czf /backup/n8n-backup-$(date +%F).tar.gz -C /data .
```
