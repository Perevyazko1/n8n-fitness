# CLAUDE.md

Заметки для Claude Code по этому репозиторию.

## Что это

Репозиторий для self-hosted деплоя **n8n** через Docker Compose. Используется как
персональный фитнес-ассистент: Telegram → n8n → OpenAI → Google Sheets.

В репо лежит **только инфраструктура** (compose, env-шаблон, README). Сами
workflow'ы конфигурируются внутри UI n8n и (опционально) экспортируются JSON'ом.

## Структура

- `docker-compose.yml` — сервисы `n8n` + `caddy` (reverse proxy + TLS)
- `Caddyfile` — конфиг реверс-прокси на `n8n:5678`, авто-LE через `tls {$ACME_EMAIL}`
- `.env.example` — шаблон, реальный `.env` в git не коммитится
- `README.md` — инструкция по деплою для человека
- `.gitignore` — `.env`, `.idea/`, `data/`, `.DS_Store`

Никаких `package.json`, `src/`, языков программирования здесь нет и не должно быть.

## Правила работы

- **Коммиты делает только пользователь.** Никогда не запускай `git commit` /
  `git push` сам, даже если задача выглядит завершённой. Можно `git status`,
  `git diff` для проверки.
- Не плоди файлы без запроса (особенно `*.md`, доки, планы).
- Не возвращай в репо удалённое: TS-скаффолдинг (`src/`, `tsconfig.json`,
  `package.json`) был намеренно вычищен.
- Секреты и IP — только через `.env`, не хардкодить в `docker-compose.yml`.

## Текущее состояние инфраструктуры

- Домен: `n8n-fitness.ru` (нужен A-record на IP сервера).
- Таймзона: `Europe/Moscow` (СПб).
- HTTPS через Caddy + Let's Encrypt (`tls {$ACME_EMAIL}`). Порт 5678 наружу
  не публикуется — только через Caddy на 80/443.
- Сервера ещё нет, деплой впереди.

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
