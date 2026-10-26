# WORKLOG — Vocab Bot

Второй, отдельный Telegram-бот: 1000 английских слов по Leitner-SRS. Свой бот-токен и свой
credential в n8n, с фитнес-ботом не пересекается.

## Что где лежит

| Файл | Что это |
|---|---|
| `Vocab_Bot.json` | один воркфлоу на три триггера: Telegram + кроны 09:00 и 19:00; кроны входят в те же ветки, что и команды `/learn` и `/test` |
| `schema.sql` | таблицы `vocab_word`, `vocab_user`, `vocab_progress`, `vocab_session` |
| `words_seed.sql` | 1000 слов |

Живёт в той же Postgres, что и фитнес (таблицы `vocab_*`). Django о них не знает — работа идёт
Postgres-нодами напрямую, Mini App под словарь не планируется.

Применение SQL — команды в шапке `schema.sql`.
