"""
kaspi-pay: данные для Mini App Kaspi-бота — траты, фильтры, лимит на период, правки.

Таблицы kaspi_* — не Django-модели: их пишет n8n (воркфлоу Kaspi_Statement_Bot), схема в
kaspi-pay/sql/schema.sql. Здесь только сырой SQL, migrate их не трогает.

- В траты идут kind IN ('purchase', 'fx_diff'). В таблице суммы со знаком (покупка < 0),
  наружу «трата» положительная, возврат — отрицательный.
- Категория и «вне лимита»: ручная правка траты → правило продавца → 'other' / false.
- Лимит общий на всех: считает траты всех карт и категорий, кроме «вне лимита».
- «Сегодня» — по Вьетнаму (Asia/Ho_Chi_Minh).
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import connection, transaction

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SPEND_KINDS = ["purchase", "fx_diff"]
PERIODS = ("day", "yesterday", "week", "month", "custom")
CATEGORIES = {
    "shops": "Магазины и продукты",
    "cafe": "Кафе и рестораны",
    "transport": "Транспорт",
    "fun": "Развлечения",
    "housing": "Жильё и связь",
    "subs": "Подписки и сервисы",
    "health": "Здоровье",
    "other": "Прочее",
}
FRIDAY = 4
MAX_BUDGET_DAYS = 92

# Резолв категории и «вне лимита» для строки e (+ правило r).
_RESOLVED = """
    COALESCE(e.category, r.category, 'other') AS category,
    COALESCE(e.exclude_budget, r.exclude_budget, false) AS excluded
"""
_FROM = """
  FROM kaspi_expenses e
  LEFT JOIN kaspi_merchant_rules r ON r.merchant_norm = e.merchant_norm
"""


class KaspiError(Exception):
    pass


def today_vn():
    return datetime.now(TZ).date()


def _d(s, field):
    try:
        return date.fromisoformat(str(s))
    except (TypeError, ValueError):
        raise KaspiError(f"bad_{field}")


def period_range(period, today=None, start=None, end=None):
    today = today or today_vn()
    if period == "day":
        return today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if period == "week":                       # календарная неделя: с понедельника
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    if period == "custom":
        s, e = _d(start, "from"), _d(end, "to")
        if e < s or (e - s).days > 366:
            raise KaspiError("bad_range")
        return s, e
    raise KaspiError("bad_period")


def default_budget_range(today=None):
    """Пт–Чт: ближайшая пятница (сегодня, если пятница) и 6 дней после неё."""
    today = today or today_vn()
    start = today + timedelta(days=(FRIDAY - today.weekday()) % 7)
    return start, start + timedelta(days=6)


def _f(v):
    return float(v) if v is not None else None


def _spend(amount):
    return -float(amount) if amount is not None else None


# ---------- чтение ----------
def _cards():
    with connection.cursor() as cur:
        cur.execute("""SELECT DISTINCT e.card, c.label
                         FROM kaspi_expenses e LEFT JOIN kaspi_cards c ON c.card = e.card
                        WHERE e.card IS NOT NULL ORDER BY e.card""")
        return [{"card": card, "label": f"{label or 'Карта'} *{card}"} for card, label in cur.fetchall()]


def budget_status(today=None):
    today = today or today_vn()
    with connection.cursor() as cur:
        cur.execute("""SELECT id, start_date, end_date, limit_rub FROM kaspi_budgets
                        WHERE start_date <= %s ORDER BY start_date DESC, id DESC LIMIT 1""", [today])
        row = cur.fetchone()
        cur.execute(f"""SELECT COALESCE(sum(e.amount_rub), 0) {_FROM}
                         WHERE e.kind = ANY(%s) AND e.op_date = %s
                           AND NOT COALESCE(e.exclude_budget, r.exclude_budget, false)""", [SPEND_KINDS, today])
        today_spent = _spend(cur.fetchone()[0]) or 0.0
        cur.execute("SELECT limit_rub FROM kaspi_budgets ORDER BY created_at DESC, id DESC LIMIT 1")
        last = cur.fetchone()

        out = {"today": today.isoformat(), "today_spent_rub": round(today_spent, 2), "active": None}
        if row:
            bid, start, end, limit = row
            cur.execute(f"""SELECT e.op_date, sum(e.amount_rub) {_FROM}
                             WHERE e.kind = ANY(%s) AND e.op_date BETWEEN %s AND %s
                               AND NOT COALESCE(e.exclude_budget, r.exclude_budget, false)
                             GROUP BY e.op_date""", [SPEND_KINDS, start, end])
            by_day = {d: _spend(s) or 0.0 for d, s in cur.fetchall()}
            spent = sum(by_day.values())
            ended = today > end
            days_left = 0 if ended else (end - today).days + 1
            left = float(limit) - spent
            out["active"] = {
                "id": bid, "start": start.isoformat(), "end": end.isoformat(),
                "limit_rub": float(limit), "spent_rub": round(spent, 2), "left_rub": round(left, 2),
                "days_left": days_left, "per_day_rub": round(left / days_left, 2) if days_left and left > 0 else 0,
                "ended": ended,
                "days": [{"date": (start + timedelta(days=i)).isoformat(),
                          "rub": round(by_day.get(start + timedelta(days=i), 0.0), 2)}
                         for i in range((end - start).days + 1)],
            }
    # что подставить в шторку «Новый лимит»
    if out["active"] and out["active"]["ended"]:
        ns = date.fromisoformat(out["active"]["end"]) + timedelta(days=1)
        if ns < today:                         # пропустили несколько недель — к ближайшей пятнице
            ns, ne = default_budget_range(today)
        else:
            ne = ns + timedelta(days=6)
    else:
        ns, ne = default_budget_range(today)
    out["next_default"] = {"start": ns.isoformat(), "end": ne.isoformat(),
                           "limit_rub": float(last[0]) if last else None}
    return out


def summary(period, start=None, end=None, card=None, category=None):
    p_start, p_end = period_range(period, start=start, end=end)
    if category and category not in CATEGORIES:
        raise KaspiError("bad_category")
    where, params = ["e.kind = ANY(%s)", "e.op_date BETWEEN %s AND %s"], [SPEND_KINDS, p_start, p_end]
    if card:
        where.append("e.card = %s")
        params.append(str(card))
    with connection.cursor() as cur:
        cur.execute(f"""SELECT e.id, e.card, e.op_date, e.kind, e.merchant, e.merchant_norm,
                               e.amount_kzt, e.amount_rub, e.orig_amount, e.orig_currency,
                               (SELECT count(*) FROM kaspi_expenses x
                                 WHERE x.merchant_norm = e.merchant_norm AND x.kind = 'purchase') AS m_count,
                               {_RESOLVED}
                          {_FROM}
                         WHERE {' AND '.join(where)}
                         ORDER BY e.op_date DESC, e.id""", params)
        rows = cur.fetchall()
        cur.execute("SELECT max(op_date), max(created_at) FROM kaspi_expenses")
        last_op, last_upload = cur.fetchone()

    cats = {k: {"key": k, "label": v, "rub": 0.0, "excluded_rub": 0.0} for k, v in CATEGORIES.items()}
    items, days = [], {}
    total_kzt = total_rub = excl_rub = fx_kzt = 0.0
    no_rate = False
    for (eid, card_, op_date, kind, merchant, mnorm, kzt, rub, orig, cur_code, m_count, cat, excluded) in rows:
        cat = cat if cat in CATEGORIES else "other"
        s_kzt, s_rub = _spend(kzt), _spend(rub)
        no_rate |= s_rub is None
        # разбивка по категориям — по всем тратам периода/карты (до фильтра категории),
        # чтобы карточка категорий не схлопывалась в одну полосу при выборе фильтра
        cats[cat]["excluded_rub" if excluded else "rub"] += s_rub or 0.0
        if category and cat != category:
            continue
        d = days.setdefault(op_date.isoformat(), {"date": op_date.isoformat(), "rub": 0.0, "excluded_rub": 0.0})
        d["excluded_rub" if excluded else "rub"] += s_rub or 0.0
        if excluded:
            excl_rub += s_rub or 0.0
        else:
            total_kzt += s_kzt
            total_rub += s_rub or 0.0
        if kind == "fx_diff":                  # курсовая разница — только в суммы, не строкой
            fx_kzt += s_kzt
            continue
        items.append({
            "id": eid, "date": op_date.isoformat(), "merchant": merchant, "merchant_norm": mnorm,
            "kzt": round(s_kzt, 2), "rub": round(s_rub, 2) if s_rub is not None else None,
            "orig": abs(_f(orig)) if orig is not None else None, "cur": cur_code,
            "refund": s_kzt < 0, "card": card_, "category": cat, "excluded": bool(excluded),
            "merchant_count": m_count,
        })

    return {
        "ok": True,
        "period": period, "from": p_start.isoformat(), "to": p_end.isoformat(),
        "filters": {"card": card or None, "category": category or None},
        "total_rub": round(total_rub, 2), "total_kzt": round(total_kzt, 2),
        "excluded_rub": round(excl_rub, 2), "fx_kzt": round(fx_kzt, 2),
        "count": len(items), "no_rate": no_rate,
        "days": [{**d, "rub": round(d["rub"], 2), "excluded_rub": round(d["excluded_rub"], 2)} for d in days.values()],
        "categories": [{**c, "rub": round(c["rub"], 2), "excluded_rub": round(c["excluded_rub"], 2)}
                       for c in sorted(cats.values(), key=lambda c: -(c["rub"] + c["excluded_rub"]))
                       if c["rub"] or c["excluded_rub"]],
        "category_labels": CATEGORIES,
        "cards": _cards(),
        "budget": budget_status(),
        "items": items,
        "last_op_date": last_op.isoformat() if last_op else None,
        "last_upload": last_upload.isoformat() if last_upload else None,
    }


# ---------- запись ----------
def budget_set(start, end, limit_rub, user_id=None):
    s, e = _d(start, "start"), _d(end, "end")
    if e < s or (e - s).days + 1 > MAX_BUDGET_DAYS:
        raise KaspiError("bad_range")
    try:
        limit = round(float(limit_rub), 2)
    except (TypeError, ValueError):
        raise KaspiError("bad_limit")
    if not 0 < limit < 100_000_000:
        raise KaspiError("bad_limit")
    with connection.cursor() as cur:
        cur.execute("""INSERT INTO kaspi_budgets (start_date, end_date, limit_rub, created_by)
                       VALUES (%s, %s, %s, %s) RETURNING id""", [s, e, limit, user_id])
        return cur.fetchone()[0]


_UNSET = object()


@transaction.atomic
def expense_update(expense_id, category=_UNSET, excluded=_UNSET, apply_to_merchant=False):
    """Правка траты. apply_to_merchant: записать в правило продавца (source=manual) и снять ручные
    правки с его трат, чтобы правило действовало на все прошлые и будущие."""
    if category is not _UNSET and category not in CATEGORIES:
        raise KaspiError("bad_category")
    if excluded is not _UNSET and not isinstance(excluded, bool):
        raise KaspiError("bad_excluded")
    if category is _UNSET and excluded is _UNSET:
        raise KaspiError("nothing_to_update")
    with connection.cursor() as cur:
        cur.execute("SELECT merchant_norm FROM kaspi_expenses WHERE id = %s", [expense_id])
        row = cur.fetchone()
        if not row:
            raise KaspiError("not_found")
        mnorm = row[0]
        if apply_to_merchant:
            cur.execute("SELECT category, exclude_budget FROM kaspi_merchant_rules WHERE merchant_norm = %s", [mnorm])
            rule = cur.fetchone() or ("other", False)
            new_cat = rule[0] if category is _UNSET else category
            new_exc = rule[1] if excluded is _UNSET else excluded
            cur.execute("""INSERT INTO kaspi_merchant_rules (merchant_norm, category, exclude_budget, source, updated_at)
                           VALUES (%s, %s, %s, 'manual', now())
                           ON CONFLICT (merchant_norm) DO UPDATE SET category = EXCLUDED.category,
                                  exclude_budget = EXCLUDED.exclude_budget, source = 'manual', updated_at = now()""",
                        [mnorm, new_cat, new_exc])
            sets = []
            if category is not _UNSET:
                sets.append("category = NULL")
            if excluded is not _UNSET:
                sets.append("exclude_budget = NULL")
            cur.execute(f"UPDATE kaspi_expenses SET {', '.join(sets)} WHERE merchant_norm = %s", [mnorm])
            return {"merchant_norm": mnorm, "scope": "merchant", "affected": cur.rowcount}
        sets, params = [], []
        if category is not _UNSET:
            sets.append("category = %s")
            params.append(category)
        if excluded is not _UNSET:
            sets.append("exclude_budget = %s")
            params.append(excluded)
        cur.execute(f"UPDATE kaspi_expenses SET {', '.join(sets)} WHERE id = %s", params + [expense_id])
        return {"merchant_norm": mnorm, "scope": "expense", "affected": cur.rowcount}

