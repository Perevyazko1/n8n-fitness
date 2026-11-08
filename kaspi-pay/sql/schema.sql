-- kaspi-pay — учёт трат Kaspi QR во Вьетнаме. Таблицы kaspi_* в общей БД (контейнер db),
-- как vocab_*/reels_*: Django о них не знает, работает только n8n.
--
-- Применение (на VPS, делает пользователь):
--   docker compose exec -T db psql -U fitness -d fitness < kaspi-pay/sql/schema.sql

-- Курс ЦБ РФ, кэш раз в сутки. day — наш день кэша (по Москве), cbr_date — дата курса у ЦБ.
-- Курсы уже приведены к 1 единице: сколько рублей за 1 ₸ и за 1 ₫.
CREATE TABLE IF NOT EXISTS kaspi_fx_rates (
    day        date PRIMARY KEY,
    cbr_date   date,
    kzt_rub    numeric(14, 8) NOT NULL,
    vnd_rub    numeric(16, 10),            -- NULL, если ЦБ не отдал донг
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- Одна строка = одна операция. Храним исходные суммы, курс и пересчёт в рубли.
CREATE TABLE IF NOT EXISTS kaspi_expenses (
    id            bigserial PRIMARY KEY,
    op_at         timestamptz NOT NULL,     -- момент операции (локальное время Вьетнама → UTC)
    op_date       date NOT NULL,            -- день операции по Вьетнаму (для итогов)
    time_known    boolean NOT NULL DEFAULT true,  -- false: на экране истории была только дата
    merchant      text NOT NULL,
    merchant_norm text NOT NULL,            -- нижний регистр, без диакритики и знаков — для дедупа
    type          text NOT NULL DEFAULT 'purchase',  -- purchase | refund
    amount_kzt    numeric(14, 2),           -- реально списано Kaspi (основа пересчёта)
    amount_vnd    numeric(16, 0),
    amount_rub    numeric(14, 2),
    rub_source    text,                     -- kzt | vnd — из какой суммы посчитаны рубли
    rate_day      date,                     -- какой день кэша курса применён
    kzt_rub       numeric(14, 8),
    vnd_rub       numeric(16, 10),
    amount_key    text NOT NULL,            -- 'kzt2900.00' или 'vnd150000', если ₸ не видно
    dedup_key     text NOT NULL UNIQUE,     -- 'YYYY-MM-DDTHH:MM|amount_key|merchant_norm'
    raw_text      text,                     -- OCR-текст скриншота, для разбора ошибок
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS kaspi_expenses_op_date_idx ON kaspi_expenses (op_date);
