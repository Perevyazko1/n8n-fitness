# План миграции: Google Sheets → Postgres + Django

Статус: **черновик плана** (код ещё не пишем). Составлен 2026-06-05.
Цель — уйти от Sheets-как-БД (костыли с номерами строк, чтение целых листов,
дублирование auth) к нормальной реляционной БД и бэкенду на Django.

## Принципы (что НЕ ломаем)

1. **Один источник правды.** Главный риск — split-brain: Mini App пишет в Postgres,
   а бот (n8n Phase_3) продолжает в Sheets. Для общих сущностей (`food_log`,
   `workout_log`, …) переключаем Mini App И бота на Postgres **в одно окно**.
2. **Контракты вебхуков не меняются** → фронт (Mini App) почти не трогаем (только `API_BASE`).
   Эндпоинты см. в `../n8n-fitness-scan/CLAUDE.md`.
3. **Бот не переписываем на Django сразу.** n8n умеет в Postgres напрямую (Postgres-нода) —
   меняем только Google Sheets-ноды → Postgres-ноды, LLM-оркестрация остаётся в n8n.

## Ограничения сервера (важно!)

`217.60.61.145`: **1 vCPU**, **1.9 ГБ RAM (свободно ~1 ГБ)**, 15 ГБ диска, 6 контейнеров
уже крутятся (n8n, nginx, django-back, mtproto, wireguard, 3x-ui). Существующий
`django-back` (проект `vacuum_remote`) — на **SQLite**, host-network gunicorn:8000.

### РЕШЕНО (2026-06-05)
- **VPN/прокси-сервисы НЕ трогаем** — все нужны (mtproto, 3x-ui, amnezia-wg, django-back).
- **+2 ГБ swap** (сейчас swap=0!) — обязательный первый шаг, снимает давление по RAM:
  ```bash
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  ```
- **Postgres локально** (не managed) — контейнер `postgres:16-alpine` в НАШЕМ
  `docker-compose.yml` рядом с n8n. Тюнинг по-маленькому (`shared_buffers=96MB`,
  `max_connections=20`). Резидент ~120–180 МБ. С учётом ~1 ГБ available + swap — влезает.
- **Django — отдельный сервис, но в том же `docker-compose.yml`** (рядом с n8n + db).
  Изоляция от `vacuum_remote`, НО переиспользуем домен `n8n-fitness.ru` — без новых DNS/cert.
  1 gunicorn-воркер для начала (~80–120 МБ).
- Почему Postgres, а не SQLite: и n8n, и Django пишут конкурентно; n8n ходит в PG родной
  Postgres-нодой по имени сервиса `db` (общая сеть compose). SQLite, расшаренный между
  контейнерами, хрупок (локи, нет сетевого доступа).

## Целевая архитектура

Один `docker-compose.yml` (наш): сервисы `n8n` + `db` (postgres) + `api` (django).
Общая сеть compose → `n8n` и `api` ходят в `db` по имени сервиса. Наружу — существующий
host-network nginx по домену `n8n-fitness.ru`:
- `location /` → `127.0.0.1:5678` (n8n, как сейчас)
- `location /api/` → `127.0.0.1:8001` (django) ← **добавляем один блок, тот же домен/cert**
- `db` (postgres) наружу НЕ публикуем (только внутри compose; опц. `127.0.0.1:5432` для импорта).

Порты: n8n=5678, django-back(чужой)=8000 занят → наш django **8001**.

```
Telegram Mini App ──HTTPS──► nginx /api/ ──► Django (gunicorn:8001)  ─┐
   (фронт: API_BASE=                            initData-auth         │
    https://n8n-fitness.ru/api)                                       ▼
Telegram чат ──► n8n Phase_3 (LLM-бот) ──Postgres-нода(db:5432)──► Postgres (db)
   (логика в n8n, Sheets-ноды → PG)                                   ▲
Apple Watch (бэклог) ──► n8n/Django ──────────────────────────────────┘
```

## Схема БД (из листов, + задел на мультиюзер)

Сейчас всё single-user. Заводим `users` сразу, на все логи — FK `user_id`. При импорте
все строки → единственному существующему юзеру.

| Таблица | Поля | Ключи/прим. |
|---|---|---|
| `users` | id, telegram_id (bigint, uniq), first_name, created_at | telegram_id из initData |
| `profiles` | user(1:1), height_cm, weight_kg, age, sex, activity_level, goal, daily_baseline_kcal, bmr, training_days_interval, target_kcal, target_protein_g, target_fat_g, target_carbs_g, updated_at | |
| `food_log` | id, user FK, date, time, description, kcal, protein, fat, carbs, meal_type, created_at | индекс (user, date) |
| `workout_log` | id, user FK, date, day_plan, exercises_done, duration_min, kcal_burned, notes, created_at | **uniq (user, date)** → upsert «завершить тренировку» |
| `workout_done` | id, user FK, date, block_num, exercise, done(bool), updated_at | **uniq (user, date, block_num, exercise)** |
| `walking_log` | id, user FK, date, time, activity, duration_min, distance_km, speed_kmh, kcal_burned, notes | |
| `body_params` | id, user FK, date, weight, body_fat_pct, notes | |
| `products` | id, barcode (uniq), name, aliases, kcal_per_100g, protein_per_100g, fat_per_100g, carbs_per_100g, default_serving_g, notes | глобальный справочник |
| `workouts_catalog` | id, user FK, block_num, group, exercise, sets, reps, weight, note, met, default_min | план юзера (был `workouts_flat`) |
| `workout_blocks` | id, user FK, block_num, label, active(bool) | конфиг блоков плана |

Типы: kcal — int, макросы/вес/met — numeric. date — date, time — time/text.

## API (= существующие контракты + 2 новые фичи)

Все под одним Django-сервисом, auth — middleware (проверка Telegram `initData` HMAC, **один
раз** вместо 7 копий в n8n). Эндпоинты (пути сохраняем как у n8n-вебхуков):

- `POST /api/dashboard` — состояние на сегодня (перенос логики `Compute Dashboard`).
- `POST /api/food-log` — записи за день (принимает `date`). **backdating: тривиально (WHERE date=)**.
- `POST /api/delete-food` — удаление по id (а не по номеру строки! — уходит весь костыль сверки).
- `POST /api/repeat-food` — копия позиции (принимает целевую `date` — backdating).
- `POST /api/workout-today` — план + галочки (принимает `date`).
- `POST /api/toggle-exercise` — upsert галочки (есть `date`).
- `POST /api/complete-workout` — **НОВОЕ**: upsert `workout_log` за `date` (day_plan по циклу,
  kcal_burned = MET-оценка, позже заменится Apple Watch). Закрывает «галочки ни на что не влияют».
- `POST /api/scan-barcode` — лог по штрихкоду (перенос Barcode).
- (бэклог) `POST /api/log-workout-burn` — Apple Watch, токен-auth.

**Backdating** на реальной БД — это просто параметр `date` в запросе/INSERT, без номеров строк.
Общий расчёт (`expected_today`, цели, дефицит) — **одна функция/сервис** вместо 3 дублей
(`Build Context` / `Dashboard` / `WorkoutToday`).

## Порядок миграции (стадийно, без split-brain)

1. **Инфра:** swap 2 ГБ (команды выше). В наш `docker-compose.yml` добавить `db`
   (postgres:16-alpine, именованный том, tuning, `127.0.0.1:5432` опц.) и `api`
   (django/gunicorn, `127.0.0.1:8001`, env `DATABASE_URL` на `db`). В существующий
   `nginx.conf` (vacuum_remote) добавить в vhost `n8n-fitness.ru` блок
   `location /api/ { proxy_pass http://127.0.0.1:8001; }` **перед** `location /`. Тот же cert.
2. **Django:** модели (выше) + миграции + middleware initData + 8 эндпоинтов + общий сервис
   расчёта. Покрыть тестами ключевые расчёты (перенести из n8n как есть, сверить числа).
3. **Импорт данных:** разовый скрипт Sheets → Postgres (через service-account, тот же
   `Google Sheets (SA)`), маппинг лист→таблица, все строки → существующему юзеру.
4. **Go-live окно (атомарно для общих сущностей):**
   a. финальный до-импорт (чтобы не потерять свежие записи);
   b. Mini App: `API_BASE` → Django;
   c. бот: Google Sheets-ноды → Postgres-ноды (читают/пишут ту же БД).
   После этого Sheets — только архив/бэкап.
5. **Чистка n8n** (то, что отложили): слить 6 webhook-воркфлоу (их роль теперь у Django —
   можно просто выключить), слить кроны, удалить мёртвые Phase_1/Phase_2/дубль Phase_3.
6. **Позже (опц.):** увести и LLM-логику бота в Django (management command / celery),
   тогда n8n можно совсем убрать из тракта.

## Риски и митигации

- **RAM на сервере** → Postgres-tuning + swap; план Б — managed PG.
- **Split-brain** → общие сущности переключаем в одно окно (шаг 4), не по частям.
- **Расхождение расчёта при переносе** → тесты-сверка чисел Django vs n8n на реальных данных
  до переключения.
- **initData-auth тонкости** (тот же HMAC, что в n8n `Validate & Parse`) → переносим 1:1,
  тест на реальном initData.
- **Откат:** Sheets остаются нетронутыми до подтверждения → быстрый rollback (вернуть
  `API_BASE` и ноды бота на Sheets).

## Оценка усилий (Claude пишет, пользователь деплоит)

- Инфра (compose + PG + nginx + swap): ~0.5 дня (деплой — пользователь).
- Django (модели, auth, 8 эндпоинтов, расчёт, тесты): ~2–3 дня.
- Импорт данных: ~0.5 дня.
- Cutover Mini App + 2 новые фичи (complete-workout, backdating UI): ~0.5–1 день.
- Репойнт бота n8n → Postgres (аккуратно, с тестами): ~1–2 дня.
- **Итого ~5–7 сфокусированных дней**, стадийно, с паузами.

## Решения (зафиксировано 2026-06-05)

1. ✅ **Postgres локально** на сервере (контейнер в нашем compose) + swap. Не managed.
2. ✅ **Отдельный сервис**, но в том же `docker-compose.yml` рядом с n8n (изоляция кода +
   переиспользование домена). НЕ подселяем в `vacuum_remote`.
3. ✅ **Путь `n8n-fitness.ru/api`** (один `location`-блок, тот же cert). Без поддомена.
4. ✅ **Голые Django-вьюхи + JSON** (без DRF) — легче на 1 CPU, эндпоинтов мало.
5. ✅ **Всё сразу** — мигрируем все 9 сущностей и переключаем в одно окно.

## Прогресс

### Сделано (2026-06-05) — шаги 1–2 код-комплит, ждёт деплоя
- Инфра: `docker-compose.yml` (+ `db` Postgres, + `api` Django), `backend/Dockerfile`,
  `nginx-n8n.conf` (+ `location /api/`), `.env.example` (+ DJANGO/POSTGRES).
- Django `backend/`: модели всех 9 сущностей + `TgUser` (уник-ключи: `workout_log(user,date)`,
  `workout_done(user,date,block_num,exercise)`); auth initData (порт из n8n); middleware
  (auth+CORS); расчёт `calc.py` (`expected_today`/цели/дашборд/план — единое место);
  все эндпоинты + новый `complete-workout` + backdating; `delete-food` по `id`.
- Синтаксис Python и `docker compose config` — валидны.

### Сделано (2026-06-05, продолжение)
- Скрипт импорта (шаг 3): `backend/fitness/management/commands/import_sheets.py` — читает
  один `.xlsx`-экспорт всей таблицы (openpyxl), маппит 9 вкладок в модели, юзер по
  `profile.chat_id`. Флаги `--dry-run` / `--wipe`. Идемпотентно (в транзакции).

### Развёрнуто на сервере (2026-06-05) ✅
- `0001_initial.py` сгенерён и сохранён локально (`backend/fitness/migrations/`) — **закоммитить**.
- swap 2 ГБ добавлен (persistent). db+api подняты, `migrate` применён.
- Данные импортированы: profile 1, food_log 130, workout_log 14, workout_done 1,
  walking_log 7, body_params 1, products 4, workouts_flat 32, workout_blocks 4.
- nginx: `location /api/` добавлен (бэкап + `nginx -t` + reload). Внешне живо:
  `https://n8n-fitness.ru/api/health` → ok, CORS `*`. n8n не задет (/ → 200).
- Расчёт сверен на реальных данных (dashboard/workout-today считаются корректно).

### Фронт-катовер написан (2026-06-05) — НЕ деплоить до репойнта бота
- Фронт (`n8n-fitness-scan`, `?v=10`): `API_BASE` → `https://n8n-fitness.ru/api`;
  `delete-food` по `id`; страница тренировки — навигация по дням (backdating) +
  кнопка «Завершить тренировку» (`complete-workout`). Сканер переедет автоматически.

### Репойнт бота — СДЕЛАН и провалидирован (2026-06-05)
- `Fitness_Bot_Phase_3_PG.json` — 9 reads + 8 writes на Postgres (credential `PG`
  id `1Vpr6VdwzI4rfpHh`), ноль Sheets-нод. Reads — чистый SELECT (single-user, без фильтра).
  Writes — `executeQuery` с инлайн-JSON-литералом `'{{ JSON.stringify(...).replace(/'/g,"''") }}'::jsonb`
  (инъекций-безопасно, comma-safe). Delete по `id` (Compute Delete Target отдаёт `_del_id`).
- **Reads протестированы вживую**: бот ответил из PG, числа сошлись с дашбордом.
- **Весь write-SQL провалидирован** против живой схемы (ROLLBACK). Поймано/починено:
  `workout_log` без `created_at`; barcode `'bot-'+md5` > varchar(32) → `left(...,32)`.

### GO-LIVE ЗАВЕРШЁН ✅ (2026-06-05)
- Бот: `Fitness_Bot_Phase_3_PG` активен, пишет/читает Postgres (проверено: лог еды,
  пересчёт остатка, удаление по id — всё через PG).
- Mini App: задеплоен `?v=10`, `API_BASE = https://n8n-fitness.ru/api` → Django → Postgres.
- Ре-импорт не понадобился: с момента первого импорта в Sheets ничего не писалось
  (юзер подтвердил), PG = актуальное состояние.
- **Postgres — источник правды. Google Sheets заморожены (архив/бэкап).**
- Появились новые фичи: backdating (еда/тренировка), «завершить тренировку», delete по id.

### Осталось (необязательная чистка, без спешки)
- [ ] Выключить старый `Fitness_Bot_Phase_3` (Sheets-версию) — пусть полежит выключенным
      как откат на пару дней, потом удалить.
- [ ] Выключить старые webhook-воркфлоу Mini App (Dashboard/FoodLog/WorkoutToday/Toggle/
      Delete/Repeat/Barcode) — их роль теперь у Django. Бот их не использует.
- [ ] Слить кроны / удалить мёртвые Phase_1/Phase_2 (давний бэклог).
- [ ] (бэклог) Apple Watch авто-калории; «бот знает всю историю» через tool-use к PG.

⚠️ ВАЖНО: фронт `?v=10` НЕ пушить/деплоить, пока бот не репойнтнут — иначе split-brain
(приложение на PG, бот на Sheets). Выкатываем вместе.

⚠️ Сейчас: новый API живёт ПАРАЛЛЕЛЬНО. Фронт всё ещё ходит в старые n8n-вебхуки,
бот пишет в Sheets. Postgres — снимок на момент импорта. Пока НЕ источник правды
(не переключили) — свежие записи идут в Sheets. Cutover свяжет всё воедино.
