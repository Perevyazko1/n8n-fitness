# n8n-fitness

Self-hosted n8n под персонального фитнес-ассистента (Telegram + GPT + Google Sheets).

## Фазы разработки

Воркфлоу развивается итеративно. Каждая фаза — отдельный экспортируемый JSON
в корне репо.

### Phase 1 — MVP-логгер (готово)

Файл: `Fitness_Bot_Phase_1.json`.

Цель: пользователь шлёт в Telegram голос или текст про еду / тренировку / вес —
бот распознаёт намерение, пишет строку в Google Sheets и отвечает в чат.

Скоуп:
- Telegram Trigger (текст + голос).
- Транскрибация голоса через OpenAI Whisper (ru).
- Классификация намерения через GPT-4o-mini, ответ строго в JSON
  `{ action, data, reply }`, где `action ∈ {log_food, log_workout, log_body, chat}`.
- Parse + Enrich: парсит JSON из ответа модели, добавляет `chat_id`, `date`, `time`.
- Switch Action маршрутизирует по `action` в один из листов Google Sheets:
  `food_log` / `workout_log` / `body_params`. Ветка `chat` идёт сразу в ответ.
- Telegram Reply отдаёт `reply` пользователю (Markdown).

Чего нет в Phase 1 (сознательно вынесено дальше): персональные нормы КБЖУ,
сводки за день/неделю, план тренировок, напоминания, редактирование записей.

### Phase 2 — память, КБЖУ-бюджет, проактивный пинг

Файлы: `Fitness_Bot_Phase_2.json` (основной воркфлоу) и
`Fitness_Bot_Phase_2_Cron.json` (вечерний пинг). Phase 1 не трогается —
Phase 2 это отдельный workflow, который заменяет Phase 1 при активации.

Цель: бот в течение дня держит контекст ("утром сказал Трен1 — вечером
помнит"), считает остаток КБЖУ-бюджета, сам определяет какая сегодня
тренировка по циклу `№1 → отдых → №2 → отдых → №3 → отдых → №4 → отдых`
и в 23:00 ругает если запланированная тренировка пропущена.

#### Ключевые решения

- **Расписание:** чередование Трен1/Трен2/Трен3/Трен4 определяется от
  последней записи `workout_log`. Шаг — `profile.training_days_interval`
  (по умолчанию 1, "через день"). Плана по дням недели нет.
- **Целевые КБЖУ:** один лист `profile`, формула Mifflin-St Jeor. Если
  юзер прямо называет цель ("хочу 1900 ккал") — `set_goals` перезаписывает
  `target_kcal` точечно.
- **Пинг:** один cron в 23:00 МСК, одно сообщение если ожидалась
  тренировка и записи в `workout_log` за сегодня нет.
- **Память:** короткая история диалога и текущее намерение (`plan_workout`)
  живут в `$workflow.staticData` n8n, ключ — `chat_id`. На следующий день
  намерение сбрасывается. Долгосрочные данные — в Sheets.

#### Изменения в Sheets перед запуском

В лист `profile` дописать вручную колонки:
- `goal` (значения `lose` / `maintain` / `gain`)
- `training_days_interval` (число, по умолчанию `1`)
- `bmr` (число — рассчитается ботом при `set_profile` или впишешь вручную)
- `daily_baseline_kcal` (число — фоновая активность кроме ходьбы и
  тренировок, по умолчанию `280`)
- `target_protein_g` (без точки на конце — n8n матчит по точному имени)

Порядок остальных колонок не менять. Лист `user_profile` не используется
(можно оставить пустым).

**Лист `workouts_flat`** — плоская версия программы тренировок,
которую читает бот. Колонки:

| block_num | group | exercise | default_min | met | sets | reps | weight | note |

- `block_num` — номер тренировки (1-4).
- `default_min` — типичное время в минутах на упражнение (силовое 4-5,
  эллипс 20, скакалка 5).
- `met` — метаболический эквивалент (интенсивность). Силовая изоляция
  3.5, компаунд 5-6, кардио intense 10. Используется для расчёта
  расхода ккал по формуле `kcal = MET × вес × мин / 60`.
- Остальные колонки — твой план тренировок (ссылками на лист `workouts`
  для синхрона с визуальным справочником).

Бот использует лист и для утреннего пинга (план + ожидаемый расход на
сегодня), и для ответов на общие вопросы про распределение упражнений,
и для расчёта kcal_burned тренировки при `log_workout`.

**Лист `walking_log`** — записи ходьбы/походов вне плановой тренировки.
Колонки:

| date | time | activity | duration_min | distance_km | speed_kmh | kcal_burned | notes |

Заполняется ботом при action `log_walking`. Activity — например
`treadmill_walking`, `hiking`, `running`. Расход ккал считается по MET
ходьбы в зависимости от скорости.

**Опциональный лист `products`** — справочник часто употребляемых продуктов.
Если бот должен использовать точные цифры с упаковок вместо оценок GPT,
создай лист с шапкой:

| name | aliases | kcal_per_100g | protein_per_100g | fat_per_100g | carbs_per_100g | default_serving_g | notes |

- `name` — основное имя продукта (по нему ищет бот).
- `aliases` — синонимы через запятую (`nature valley, нэйчер вэлли`).
- `*_per_100g` — числа с упаковки на 100г.
- `default_serving_g` — стандартный вес одной штуки/порции (для
  батончиков, яиц). Тогда фраза «съел один» автоматически даёт ккал.
- `notes` — пометки.

Если продукт упомянут пользователем и есть в `products` — бот использует
точные цифры. Если нет — действуют обычные правила (просит граммовку или
оценивает по типичной порции). Лист может оставаться пустым — воркфлоу
не упадёт.

#### Расширенный набор `action` от модели

В дополнение к Phase 1 (`log_food`, `log_workout`, `log_body`, `chat`):
- `set_profile` — антропометрия → запись в `profile` + расчёт `target_*`.
- `set_goals` — ручной override `target_kcal` или `training_days_interval`.
- `plan_workout` — "сегодня Трен N", в Sheets не пишется, остаётся в памяти.
- `daily_summary` — сводка по сегодняшним КБЖУ.
- `show_workout` — список упражнений на сегодня из листа `workouts`.

#### Архитектура воркфлоу

```
Telegram → Voice?/Text → Merge
       → Read Profile / Food Log / Workout Log / Workouts Catalog (sequential, executeOnce)
       → Build Context (агрегация + staticData-память + expected_today)
       → GPT-4o-mini (system-промпт со встроенным <context>)
       → Parse + Enrich → Save Memory
       → Switch (food / workout / body / set_profile / set_goals / passthrough)
       → Sheets-операции → Telegram Reply
```

#### Cron-воркфлоу (проактивные сообщения)

Три отдельных файла, можно включать/выключать независимо:

| Файл | Расписание | Что делает |
|---|---|---|
| `Fitness_Bot_Phase_2_Morning.json` | 08:00 МСК ежедневно | Шлёт план дня: тренировка/отдых, цель ккал/белка, список упражнений из `workouts` если день тренировки. Без GPT, текст детерминирован. |
| `Fitness_Bot_Phase_2_Cron.json` | 23:00 МСК ежедневно | Если по циклу ожидалась тренировка и в `workout_log` за сегодня нет записи — ругательное напоминание. |
| `Fitness_Bot_Phase_2_Weekly.json` | Воскресенье 21:00 МСК | Сводка за 7 дней: динамика веса/жира, выполненные тренировки, средние ккал/белок, % дней с добранным белком, оценка темпа. Без GPT. |

#### Разворачивание

1. В Google Sheets добавить колонки `goal`, `training_days_interval`
   в лист `profile` (если ещё не добавлены).
2. Импортировать `Fitness_Bot_Phase_2.json` в n8n.
3. **Деактивировать Phase 1** (один Telegram webhook на оба не уживётся).
4. Активировать Phase 2.
5. Импортировать `Fitness_Bot_Phase_2_Cron.json`, `Fitness_Bot_Phase_2_Morning.json`,
   `Fitness_Bot_Phase_2_Weekly.json` и активировать (любые из них опционально).
6. Сценарии для проверки см. в plan-файле / истории чата.

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
