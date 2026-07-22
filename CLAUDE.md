# CLAUDE.md

Заметки для Claude Code по этому репозиторию.

## Что это

Репозиторий для self-hosted деплоя **n8n** через Docker Compose. Используется как
персональный фитнес-ассистент: Telegram → n8n → OpenAI → Google Sheets.

В репо лежит **только инфраструктура** (compose, env-шаблон, README). Сами
workflow'ы конфигурируются внутри UI n8n и (опционально) экспортируются JSON'ом.

## Структура

- `docker-compose.yml` — сервисы `n8n` + `db` (Postgres) + `api` (Django), общая сеть
- `nginx-n8n.conf` — vhost: `/` → n8n, `/api/` → Django (встраивается в существующий nginx)
- `backend/` — **Django-бэкенд Mini App** (Postgres). Появился при переезде с Google Sheets,
  см. `MIGRATION_PLAN.md`. Сюда переезжают эндпоинты, которые раньше были n8n-вебхуками.
- `MIGRATION_PLAN.md` — план/решения по миграции Sheets → Postgres + Django
- `.env.example` — шаблон, реальный `.env` в git не коммитится
- `README.md` — инструкция по деплою
- `Fitness_Bot_*.json` — экспорты n8n-воркфлоу (бот + старые вебхуки)
- `Vocab_Bot.json` + `vocab/` — **второй, отдельный** Telegram-бот: 1000 английских
  слов по Leitner-SRS. Свой бот-токен и свой credential в n8n, с фитнес-ботом не
  пересекается. Один воркфлоу на три триггера (Telegram + кроны 09:00 и 19:00),
  кроны входят в те же ветки, что и команды `/learn` и `/test`.
  Живёт в той же БД, таблицы `vocab_*`, Django о них не знает
  (работа идёт Postgres-нодами напрямую, Mini App под словарь не планируется).
- `.gitignore` — `.env`, `.idea/`, `data/`, `.DS_Store`

ВАЖНО (обновлено 2026-06-05): раньше репо был «только инфра, без кода». Теперь тут
ОСОЗНАННО живёт Python/Django-бэкенд в `backend/` — это часть переезда на нормальную БД.
НЕ путать с старым TS-скаффолдингом (`src/`, `package.json`), который был мусором и удалён;
`backend/` — наоборот, основной код API, его не трогаем без причины.

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
- Не возвращай в репо удалённое: старый **TS**-скаффолдинг (`src/`, `tsconfig.json`,
  `package.json`) был мусором и намеренно вычищен. (Это НЕ про `backend/` — там Python/Django,
  он легитимный, см. выше.)
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

## Mini App (фронт) — отдельный репозиторий

Фронтенд Telegram Mini App живёт в соседнем репо **`../n8n-fitness-scan`**
(ванилла HTML/JS/CSS, GitHub Pages). Там же — план многостраничного приложения
(дашборд / еда / тренировка) и трекер прогресса: см. `../n8n-fitness-scan/CLAUDE.md`.

Со стороны n8n под эти страницы нужно добавить **читающие/пишущие вебхуки**
(сейчас вебхуки только пишут). Целевые эндпоинты и JSON-контракты —
в `../n8n-fitness-scan/CLAUDE.md` (раздел «Контракты»):
- `POST /webhook/dashboard` — переиспользует расчёт из `Build Context` (Phase 3);
- `POST /webhook/food-log` — записи `food_log` за сегодня;
- `POST /webhook/workout-today` + `POST /webhook/toggle-exercise` — план + галочки,
  требует нового листа `workout_done (date, block_num, exercise, done, updated_at)`.

Контракты держим стабильными — это API для будущего переезда Sheets → БД.
