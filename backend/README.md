# backend — Django API для Mini App

JSON-API под `https://n8n-fitness.ru/api`. Заменяет n8n-вебхуки (dashboard, food-log,
workout-today, toggle-exercise, delete-food, repeat-food, scan-barcode) + новые
`complete-workout` и backdating. Источник правды — Postgres (общий с ботом n8n).

Стек: Django (голые вьюхи + JSON), gunicorn, psycopg2. Без DRF/админки/сессий.
Авторизация — Telegram `initData` (HMAC) в `fitness/middleware.py`.

## Структура
```
backend/
  Dockerfile  requirements.txt
  manage.py
  config/        settings.py urls.py wsgi.py
  fitness/
    models.py       # таблицы = листы Sheets (+ TgUser, FK, уник-ключи)
    auth.py         # верификация initData (порт из n8n Validate & Parse)
    middleware.py   # initData-auth + CORS для /api/
    calc.py         # expected_today / цели / дашборд (порт из Build Context)
    views.py        # эндпоинты
    urls.py
    migrations/
```

## Деплой (пользователь; сервер — с согласования)

1. Заполнить `.env` (в корне репо): `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`,
   `TELEGRAM_BOT_TOKEN` (уже есть для n8n).
2. **Один раз** сгенерировать миграции и закоммитить их:
   ```bash
   docker compose run --rm api python manage.py makemigrations fitness
   # появится backend/fitness/migrations/0001_initial.py → git add/commit
   ```
3. Поднять БД и API (миграции применятся на старте контейнера):
   ```bash
   docker compose up -d db api
   docker compose logs -f api      # убедиться, что migrate прошёл и gunicorn слушает 8001
   ```
4. nginx: добавить `location /api/` из `../nginx-n8n.conf` в общий `nginx.conf`, затем:
   ```bash
   docker exec nginx nginx -t && docker exec nginx nginx -s reload
   ```
5. Smoke-test (health открыт без авторизации):
   ```bash
   curl -s https://n8n-fitness.ru/api/health      # {"ok": true, ...}
   ```
6. **Импорт данных** Sheets → Postgres — ПЕРЕД переключением фронта и бота.
   В Google Sheets: `File → Download → Microsoft Excel (.xlsx)` → положить рядом как
   `export.xlsx` → прогнать:
   ```bash
   # сначала примерка без записи:
   docker compose run --rm -v "$PWD/export.xlsx:/tmp/export.xlsx" api \
       python manage.py import_sheets /tmp/export.xlsx --dry-run
   # если счётчики ок — реально (с очисткой, чтобы прогон был идемпотентным):
   docker compose run --rm -v "$PWD/export.xlsx:/tmp/export.xlsx" api \
       python manage.py import_sheets /tmp/export.xlsx --wipe
   ```
   Юзер определяется по `profile.chat_id` (= telegram_id); все логи привязываются к нему.

## Локально (без сервера)
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# поднять локальный Postgres или указать свой в env
python manage.py makemigrations && python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

## Контракты
Совпадают с прежними n8n-вебхуками (см. `../../n8n-fitness-scan/CLAUDE.md`), отличия:
- `delete-food` принимает `id` (а не номер строки);
- `food-log` / `workout-today` принимают опц. `date` (backdating);
- добавлен `complete-workout` (фиксация тренировки → `workout_log`).
