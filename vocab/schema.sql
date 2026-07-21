-- Vocab Bot — схема для словарного Telegram-бота (1000 слов Skyeng).
-- Живёт в той же БД, что и фитнес (контейнер db), но отдельными таблицами
-- vocab_*. Django о них не знает и `migrate` их не трогает — это осознанно:
-- бот работает с Postgres напрямую из n8n, Mini App под словарь не планируется.
--
-- Применение (на VPS, делает пользователь):
--   docker compose exec -T db psql -U fitness -d fitness < vocab/schema.sql
--   docker compose exec -T db psql -U fitness -d fitness < vocab/words_seed.sql

-- Словарь. id = номер из PDF, он же порядок изучения (≈ по частотности).
CREATE TABLE IF NOT EXISTS vocab_word (
    id          smallint PRIMARY KEY,
    word        text NOT NULL,
    ipa         text,
    translation text NOT NULL,
    pos         text
);

-- Подписчики бота.
CREATE TABLE IF NOT EXISTS vocab_user (
    chat_id     bigint PRIMARY KEY,
    username    text,
    active      boolean  NOT NULL DEFAULT true,
    daily_new   smallint NOT NULL DEFAULT 10,   -- сколько новых слов в день
    streak      smallint NOT NULL DEFAULT 0,    -- дней подряд с пройденным тестом
    last_quiz   date,                           -- когда последний раз сдавал тест
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Leitner-прогресс по каждому слову.
-- box: 0..6, интервал повтора см. vocab_next_review().
-- learned_at ставится, когда слово сдано в направлении RU→EN из box >= 4.
CREATE TABLE IF NOT EXISTS vocab_progress (
    chat_id     bigint   NOT NULL REFERENCES vocab_user(chat_id) ON DELETE CASCADE,
    word_id     smallint NOT NULL REFERENCES vocab_word(id),
    box         smallint NOT NULL DEFAULT 0,
    next_review date     NOT NULL,
    lapses      smallint NOT NULL DEFAULT 0,
    last_result text,                            -- ok | typo | wrong
    learned_at  timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, word_id)
);

-- Главный горячий запрос: «что сегодня повторять у этого юзера».
CREATE INDEX IF NOT EXISTS vocab_progress_due_idx
    ON vocab_progress (chat_id, next_review);

-- Одна активная сессия проверки на юзера: очередь слов + текущий вопрос.
-- Нужна, чтобы понимать, к чему относится присланный текстом ответ.
CREATE TABLE IF NOT EXISTS vocab_session (
    chat_id     bigint PRIMARY KEY REFERENCES vocab_user(chat_id) ON DELETE CASCADE,
    queue       jsonb    NOT NULL DEFAULT '[]'::jsonb,  -- [word_id, ...] ещё не спрошенные
    current     smallint,                               -- word_id текущего вопроса
    mode        text,                                   -- en_ru | ru_en
    correct     smallint NOT NULL DEFAULT 0,
    total       smallint NOT NULL DEFAULT 0,
    wrong_ids   jsonb    NOT NULL DEFAULT '[]'::jsonb,  -- что завалил — для итога
    started_at  timestamptz NOT NULL DEFAULT now()
);

-- Интервалы Leitner: новый box -> через сколько дней спросить снова.
-- 1 / 3 / 7 / 16 / 35 / 90 дней. box 0 = завтра (только что ошибся или новое слово).
CREATE OR REPLACE FUNCTION vocab_next_review(box smallint)
RETURNS date LANGUAGE sql IMMUTABLE AS $$
    SELECT CURRENT_DATE + (CASE box
        WHEN 0 THEN 1
        WHEN 1 THEN 1
        WHEN 2 THEN 3
        WHEN 3 THEN 7
        WHEN 4 THEN 16
        WHEN 5 THEN 35
        ELSE 90
    END)::int;
$$;
