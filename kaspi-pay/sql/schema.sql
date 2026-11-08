-- kaspi-pay — учёт трат по выписке Kaspi Gold (PDF → бот → n8n). Таблицы kaspi_* в общей БД
-- (контейнер db), как vocab_*/reels_*: Django о них не знает, работает только n8n.
--
-- Применение (на VPS, делает пользователь):
--   docker compose exec -T db psql -U fitness -d fitness < kaspi-pay/sql/schema.sql

-- Курс ЦБ РФ, кэш раз в сутки. day — наш день кэша (по Москве), cbr_date — дата курса у ЦБ.
-- Курсы приведены к 1 единице: сколько рублей за 1 ₸ и за 1 ₫.
CREATE TABLE IF NOT EXISTS kaspi_fx_rates (
    day        date PRIMARY KEY,
    cbr_date   date,
    kzt_rub    numeric(14, 8) NOT NULL,
    vnd_rub    numeric(16, 10),            -- NULL, если ЦБ не отдал донг
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- Одна строка = одна строка выписки. Пишем ВСЕ операции, в траты идут только
-- kind IN ('purchase', 'fx_diff') — это решает чтение (summary/итоги), а не запись.
-- Суммы со знаком, как в выписке: покупка < 0, возврат и курсовая разница могут быть > 0.
CREATE TABLE IF NOT EXISTS kaspi_expenses (
    id            bigserial PRIMARY KEY,
    card          text,                     -- последние 4 цифры карты из выписки (траты двух людей)
    op_date       date NOT NULL,            -- дата из выписки (время Kaspi не даёт)
    kind          text NOT NULL,            -- purchase | fx_diff | transfer | topup | withdrawal | other
    operation     text NOT NULL,            -- как в выписке: Покупка / Перевод / Пополнение ...
    merchant      text NOT NULL,            -- колонка «Детали»
    merchant_norm text NOT NULL,            -- нижний регистр, без знаков — для дедупа
    amount_kzt    numeric(14, 2) NOT NULL,  -- реально списано/зачислено, со знаком
    orig_amount   numeric(16, 2),           -- сумма в валюте покупки, со знаком (если была)
    orig_currency text,                     -- VND, USD, ...; NULL — покупка в тенге
    amount_rub    numeric(14, 2),           -- amount_kzt × курс ЦБ
    rate_day      date,                     -- какой день кэша курса применён
    kzt_rub       numeric(14, 8),
    occ           smallint NOT NULL,        -- порядковый номер одинаковой операции внутри дня
    dedup_key     text NOT NULL UNIQUE,     -- 'card|YYYY-MM-DD|amount|kind|merchant_norm|occ'
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS kaspi_expenses_op_date_idx ON kaspi_expenses (op_date);

-- 2026-11-08: траты ведут двое → в ключ дедупа добавлена карта. Для таблиц, созданных до этого.
ALTER TABLE kaspi_expenses ADD COLUMN IF NOT EXISTS card text;

-- ===== 2026-11-08: Mini App v2 — категории, лимит на период, «вне лимита», подписи карт =====

-- Категория и «вне лимита» по продавцу. Заполняет n8n (правила + gpt-5-mini для незнакомых,
-- source = rule|llm), ручная правка из Mini App ставит source = manual. Автоматика manual не трогает.
-- Категории: shops | cafe | transport | fun | housing | subs | health | other.
CREATE TABLE IF NOT EXISTS kaspi_merchant_rules (
    merchant_norm  text PRIMARY KEY,
    category       text NOT NULL DEFAULT 'other',
    exclude_budget boolean NOT NULL DEFAULT false,
    source         text NOT NULL DEFAULT 'rule',
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Ручная правка ОДНОЙ траты. NULL — брать из правила продавца.
ALTER TABLE kaspi_expenses ADD COLUMN IF NOT EXISTS category text;
ALTER TABLE kaspi_expenses ADD COLUMN IF NOT EXISTS exclude_budget boolean;

-- Лимит на период (общий на всех). Действующий — последний по start_date среди начавшихся;
-- если его end_date уже прошла — Mini App показывает «период закончился».
CREATE TABLE IF NOT EXISTS kaspi_budgets (
    id         bigserial PRIMARY KEY,
    start_date date NOT NULL,
    end_date   date NOT NULL,
    limit_rub  numeric(14, 2) NOT NULL CHECK (limit_rub > 0),
    created_by bigint,                      -- Telegram user_id
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);

-- Подписи карт. n8n добавляет карту при первой выписке именем того, кто её прислал.
CREATE TABLE IF NOT EXISTS kaspi_cards (
    card       text PRIMARY KEY,
    label      text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== 2026-11-08: продавец = часть названия до «*» (Grab* A-A2W37… и Grab* A-A28S… — один Grab) =====
-- Ключ правила. merchant_norm в kaspi_expenses не трогаем: на нём держится дедуп выписок.
CREATE OR REPLACE FUNCTION kaspi_merchant_key(merchant text, mnorm text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN position('*' in merchant) > 1
    THEN COALESCE(NULLIF(trim(regexp_replace(lower(split_part(merchant, '*', 1)), '[^a-z0-9а-яё]+', ' ', 'g')), ''), mnorm)
    ELSE mnorm END
$$;

-- category NULL = «категорию не решали»: правило только про «вне лимита», категорию ставит автоматика.
ALTER TABLE kaspi_merchant_rules ALTER COLUMN category DROP NOT NULL;
ALTER TABLE kaspi_merchant_rules ALTER COLUMN category DROP DEFAULT;

-- Перенос правил, заведённых на отдельные «Grab* A-…», на общий ключ. Ручные важнее, среди них —
-- с настоящей категорией (не 'other'), потом самое свежее. Повторный запуск ничего не меняет.
INSERT INTO kaspi_merchant_rules (merchant_norm, category, exclude_budget, source, updated_at)
SELECT DISTINCT ON (x.k) x.k, r.category, r.exclude_budget, r.source, r.updated_at
  FROM kaspi_merchant_rules r
  JOIN LATERAL (SELECT kaspi_merchant_key(e.merchant, e.merchant_norm) AS k
                  FROM kaspi_expenses e WHERE e.merchant_norm = r.merchant_norm LIMIT 1) x ON true
 WHERE x.k <> r.merchant_norm
 ORDER BY x.k, (r.source = 'manual') DESC, (r.category IS NOT NULL AND r.category <> 'other') DESC, r.updated_at DESC
ON CONFLICT (merchant_norm) DO NOTHING;
