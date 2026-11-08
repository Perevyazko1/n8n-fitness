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
