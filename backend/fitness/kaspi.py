"""
kaspi-pay: итоги трат по выписке Kaspi Gold для Mini App Kaspi-бота.

Таблица kaspi_expenses — не Django-модель: её пишет n8n (воркфлоу Kaspi_Statement_Bot),
схема в kaspi-pay/sql/schema.sql. Здесь только читаем сырым SQL, migrate её не трогает.
В траты идут kind IN ('purchase', 'fx_diff'); суммы в таблице со знаком (покупка < 0),
наружу отдаём «трату» положительной, возврат — отрицательной.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import connection

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SPEND_KINDS = ["purchase", "fx_diff"]
PERIODS = ("day", "week", "month")


def period_range(period, today=None):
    today = today or datetime.now(TZ).date()
    if period == "day":
        return today, today
    if period == "week":                       # календарная неделя: с понедельника
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    raise ValueError(period)


def _num(v):
    return float(v) if v is not None else None


def summary(period):
    start, end = period_range(period)
    with connection.cursor() as cur:
        cur.execute(
            """SELECT card, op_date, kind, merchant, amount_kzt, amount_rub, orig_amount, orig_currency
                 FROM kaspi_expenses
                WHERE kind = ANY(%s) AND op_date BETWEEN %s AND %s
                ORDER BY op_date DESC, id""",
            [SPEND_KINDS, start, end],
        )
        rows = cur.fetchall()
        cur.execute("SELECT max(op_date), max(created_at) FROM kaspi_expenses")
        last_op, last_upload = cur.fetchone()

    items, days = [], {}
    total_kzt = total_rub = fx_kzt = 0.0
    no_rate = False
    for card, op_date, kind, merchant, kzt, rub, orig, cur_code in rows:
        spend_kzt = -float(kzt)
        spend_rub = -float(rub) if rub is not None else None
        no_rate |= spend_rub is None
        total_kzt += spend_kzt
        total_rub += spend_rub or 0.0
        d = days.setdefault(op_date.isoformat(), {"date": op_date.isoformat(), "kzt": 0.0, "rub": 0.0})
        d["kzt"] += spend_kzt
        d["rub"] += spend_rub or 0.0
        if kind == "fx_diff":                  # курсовая разница — только в итоги, не строкой
            fx_kzt += spend_kzt
            continue
        items.append({
            "date": op_date.isoformat(),
            "merchant": merchant,
            "kzt": round(spend_kzt, 2),
            "rub": round(spend_rub, 2) if spend_rub is not None else None,
            "orig": abs(_num(orig)) if orig is not None else None,
            "cur": cur_code,
            "refund": spend_kzt < 0,
            "card": card,
        })

    return {
        "ok": True,
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_kzt": round(total_kzt, 2),
        "total_rub": round(total_rub, 2),
        "fx_kzt": round(fx_kzt, 2),
        "count": len(items),
        "multi_card": len({i["card"] for i in items}) > 1,
        "no_rate": no_rate,
        "days": [{**d, "kzt": round(d["kzt"], 2), "rub": round(d["rub"], 2)} for d in days.values()],
        "items": items,
        "last_op_date": last_op.isoformat() if last_op else None,
        "last_upload": last_upload.isoformat() if last_upload else None,
    }
