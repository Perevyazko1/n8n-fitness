-- Reels-конвейер — схема для контент-бота (генерация вирусных роликов в Instagram).
-- Живёт в той же БД, что и фитнес (контейнер db), но отдельными таблицами reels_*.
-- Django о них НЕ знает и `migrate` их не трогает — как vocab_*: пайплайн работает
-- с Postgres напрямую из n8n. Единственный серверный код — ffmpeg-склейка в
-- fitness-api (эндпоинт /api/reels/assemble), и он тоже эти таблицы не читает.
--
-- Полный план: /Users/.../.claude/plans/wondrous-strolling-hinton.md
--
-- Применение (на VPS, делает пользователь):
--   docker compose exec -T db psql -U fitness -d fitness < reels/schema.sql

-- Найденные вирусные ролики-источники (только авто-режим). Дедуп по (platform, source_id):
-- один и тот же ролик не берём в работу дважды (аналог vocab NOT EXISTS/ON CONFLICT).
CREATE TABLE IF NOT EXISTS reels_sources (
    id            bigserial PRIMARY KEY,
    platform      text NOT NULL,                 -- tiktok | instagram | youtube
    source_id     text NOT NULL,                 -- id ролика на платформе
    url           text,
    metrics       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- views/likes/velocity и т.п.
    theme         text,                          -- о чём ролик (для анти-повтора тем)
    status        text NOT NULL DEFAULT 'new',   -- new | used | skipped
    discovered_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, source_id)
);

-- Сценарий = единица работы конвейера. Ядро — timeline: упорядоченный массив
-- типизированных сегментов [{type: ai|clip|image, ...}] в любом порядке (см. план).
-- origin различает два входа: auto (бот нашёл) и manual (юзер принёс мем + надиктовал).
CREATE TABLE IF NOT EXISTS reels_scripts (
    id         bigserial PRIMARY KEY,
    origin     text NOT NULL DEFAULT 'manual',   -- auto | manual
    source_id  bigint REFERENCES reels_sources(id) ON DELETE SET NULL,  -- NULL для manual
    hook       text,                             -- первые 3 сек / цепляющая фраза
    timeline   jsonb NOT NULL DEFAULT '[]'::jsonb,
    caption    text,
    hashtags   text,
    theme      text,                             -- для анти-повтора по темам
    -- Статус-машина: scripted → script_ok → assembled → video_ok → posted (| rejected).
    status     text NOT NULL DEFAULT 'scripted',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reels_scripts_status_idx ON reels_scripts (status, created_at);
-- Горячий запрос анти-повтора тем: последние N тем «избегай этих».
CREATE INDEX IF NOT EXISTS reels_scripts_theme_idx  ON reels_scripts (created_at DESC);

-- Медиа-ассеты сценария: и присланные юзером мемы (source=user), и сгенерённые
-- AI-сегменты (source=ai). kind повторяет тип сегмента таймлайна.
CREATE TABLE IF NOT EXISTS reels_assets (
    id         bigserial PRIMARY KEY,
    script_id  bigint NOT NULL REFERENCES reels_scripts(id) ON DELETE CASCADE,
    kind       text NOT NULL,                    -- clip | image (ai-видео тоже clip)
    source     text NOT NULL,                    -- user | ai
    seg_index  smallint,                         -- позиция в timeline (0..N)
    url        text,                             -- откуда качать (tg file / провайдер)
    duration   numeric(6,2),                     -- сек (обязательно для image)
    meta       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- провайдер, стоимость сегмента и т.п.
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reels_assets_script_idx ON reels_assets (script_id, seg_index);

-- Готовый склеенный ролик (после ffmpeg-сборки).
CREATE TABLE IF NOT EXISTS reels_videos (
    id         bigserial PRIMARY KEY,
    script_id  bigint NOT NULL REFERENCES reels_scripts(id) ON DELETE CASCADE,
    final_url  text,                             -- где лежит итоговый MP4 (если храним)
    duration   numeric(6,2),
    cost       numeric(8,4) NOT NULL DEFAULT 0,  -- суммарная стоимость генерации, $
    status     text NOT NULL DEFAULT 'assembled',  -- assembled | video_ok | rejected
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reels_videos_script_idx ON reels_videos (script_id);

-- Факт публикации (пока постим руками — строка ставится по кнопке «Запостил»).
CREATE TABLE IF NOT EXISTS reels_posts (
    id         bigserial PRIMARY KEY,
    video_id   bigint NOT NULL REFERENCES reels_videos(id) ON DELETE CASCADE,
    platform   text NOT NULL DEFAULT 'instagram',
    permalink  text,
    posted_at  timestamptz NOT NULL DEFAULT now()
);
