"""
kaspi-pay: данные для Mini App Kaspi-бота — траты, фильтры, лимит на период, правки.

Таблицы kaspi_* — не Django-модели: их пишет n8n (воркфлоу Kaspi_Statement_Bot), схема в
kaspi-pay/sql/schema.sql. Здесь только сырой SQL, migrate их не трогает.

- В траты идут kind IN ('purchase', 'fx_diff'). В таблице суммы со знаком (покупка < 0),
  наружу «трата» положительная, возврат — отрицательный.
- Категория и «вне лимита»: ручная правка траты → правило продавца → 'other' / false.
  Продавец для правил — kaspi_merchant_key(): часть названия до «*» (все «Grab* A-…» — один Grab).
- Лимит общий на всех: считает траты всех карт и категорий, кроме «вне лимита».
- «Сегодня» — по Вьетнаму (Asia/Ho_Chi_Minh).
"""
from datetime import date, datetime, timedelta
from statistics import median
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
# «дороже за визит» сравниваем только там, где чек ≈ цена: в магазине большой чек — это «купили много»,
# в такси — «ехали далеко». Для остальных категорий — только сумма и частота.
PRICE_CATS = {"cafe", "fun"}
MIN_VISITS = 3          # меньше — сравнения шумные
MAX_BUDGET_DAYS = 92

# Резолв категории и «вне лимита» для строки e (+ правило r).
_RESOLVED = """
    COALESCE(e.category, r.category, 'other') AS category,
    COALESCE(e.exclude_budget, r.exclude_budget, false) AS excluded
"""
_FROM = """
  FROM kaspi_expenses e
  LEFT JOIN kaspi_merchant_rules r ON r.merchant_norm = kaspi_merchant_key(e.merchant, e.merchant_norm)
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
    """Текущий период Пт–Чт: последняя пятница (сегодня, если пятница) и 6 дней после неё."""
    today = today or today_vn()
    start = today - timedelta(days=(today.weekday() - FRIDAY) % 7)
    return start, start + timedelta(days=6)


def _f(v):
    return float(v) if v is not None else None


def _spend(amount):
    return -float(amount) if amount is not None else None


# ---------- чтение ----------
def _cards():
    with connection.cursor() as cur:
        # порядок — по первой трате карты: от него зависит запасной цвет на странице
        cur.execute("""SELECT e.card, c.label, c.color
                         FROM kaspi_expenses e LEFT JOIN kaspi_cards c ON c.card = e.card
                        WHERE e.card IS NOT NULL GROUP BY e.card, c.label, c.color ORDER BY min(e.id)""")
        return [{"card": card, "name": label or "Карта", "label": f"{label or 'Карта'} *{card}", "color": color}
                for card, label, color in cur.fetchall()]


def budget_status(today=None):
    today = today or today_vn()
    with connection.cursor() as cur:
        # действующий: последний начавшийся; если он уже закончился, а следующий поставлен заранее —
        # показываем следующий как «ещё не начался»
        cur.execute("""SELECT id, start_date, end_date, limit_rub FROM kaspi_budgets
                        WHERE start_date <= %s ORDER BY start_date DESC, id DESC LIMIT 1""", [today])
        row = cur.fetchone()
        upcoming = False
        if not row or row[2] < today:
            cur.execute("""SELECT id, start_date, end_date, limit_rub FROM kaspi_budgets
                            WHERE start_date > %s ORDER BY start_date, id DESC LIMIT 1""", [today])
            nxt = cur.fetchone()
            if nxt:
                row, upcoming = nxt, True
        cur.execute(f"""SELECT COALESCE(sum(e.amount_rub), 0) {_FROM}
                         WHERE e.kind = ANY(%s) AND e.op_date = %s
                           AND NOT COALESCE(e.exclude_budget, r.exclude_budget, false)""", [SPEND_KINDS, today])
        today_spent = _spend(cur.fetchone()[0]) or 0.0
        cur.execute("SELECT limit_rub FROM kaspi_budgets ORDER BY created_at DESC, id DESC LIMIT 1")
        last = cur.fetchone()

        out = {"today": today.isoformat(), "today_spent_rub": round(today_spent, 2), "active": None}
        if row:
            bid, start, end, limit = row
            cur.execute(f"""SELECT e.op_date,
                                   sum(e.amount_rub) FILTER (WHERE NOT COALESCE(e.exclude_budget, r.exclude_budget, false)),
                                   sum(e.amount_rub) FILTER (WHERE COALESCE(e.exclude_budget, r.exclude_budget, false))
                              {_FROM}
                             WHERE e.kind = ANY(%s) AND e.op_date BETWEEN %s AND %s
                             GROUP BY e.op_date""", [SPEND_KINDS, start, end])
            rows_ = cur.fetchall()
            by_day = {d: _spend(s) or 0.0 for d, s, _ in rows_}
            excluded = sum(_spend(x) or 0.0 for _, _, x in rows_)
            spent = sum(by_day.values())
            ended = today > end
            days_left = 0 if ended else (end - max(today, start)).days + 1
            left = float(limit) - spent
            out["active"] = {
                "id": bid, "start": start.isoformat(), "end": end.isoformat(),
                "limit_rub": float(limit), "spent_rub": round(spent, 2), "left_rub": round(left, 2),
                "excluded_rub": round(excluded, 2),
                "days_left": days_left, "per_day_rub": round(left / days_left, 2) if days_left and left > 0 else 0,
                "ended": ended, "upcoming": upcoming,
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


def summary(period, start=None, end=None, card=None, category=None, only_excluded=False):
    """only_excluded — только траты «вне лимита» (переход из виджета лимита)."""
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
                               kaspi_merchant_key(e.merchant, e.merchant_norm) AS mkey,
                               NULLIF(r.name_ru, '') AS name_ru, NULLIF(r.brand, '') AS brand,
                               {_RESOLVED}
                          {_FROM}
                         WHERE {' AND '.join(where)}
                         ORDER BY e.op_date DESC, e.stmt_pos NULLS LAST, e.id""", params)
        rows = cur.fetchall()
        cur.execute("SELECT max(op_date), max(created_at) FROM kaspi_expenses")
        last_op, last_upload = cur.fetchone()
        cur.execute("""SELECT kaspi_merchant_key(merchant, merchant_norm), count(*) FROM kaspi_expenses
                        WHERE kind = 'purchase' GROUP BY 1""")
        m_counts = dict(cur.fetchall())

    cats = {k: {"key": k, "label": v, "rub": 0.0, "excluded_rub": 0.0} for k, v in CATEGORIES.items()}
    items, days = [], {}
    total_kzt = total_rub = excl_rub = fx_kzt = 0.0
    no_rate = False
    groups = {}
    for (eid, card_, op_date, kind, merchant, mnorm, kzt, rub, orig, cur_code, mkey, name_ru, brand, cat, excluded) in rows:
        cat = cat if cat in CATEGORIES else "other"
        s_kzt, s_rub = _spend(kzt), _spend(rub)
        no_rate |= s_rub is None
        # разбивка по категориям — по всем тратам периода/карты (до фильтра категории),
        # чтобы карточка категорий не схлопывалась в одну полосу при выборе фильтра
        cats[cat]["excluded_rub" if excluded else "rub"] += s_rub or 0.0
        if (category and cat != category) or (only_excluded and not excluded):
            continue
        d = days.setdefault(op_date.isoformat(), {"date": op_date.isoformat(), "rub": 0.0, "excluded_rub": 0.0})
        d["excluded_rub" if excluded else "rub"] += s_rub or 0.0
        # продавцы, сгруппированные по сети (brand от GPT), без сети — по ключу продавца
        gkey = brand.lower() if brand else mkey
        g = groups.setdefault(gkey, {"key": gkey, "name": brand or name_ru or merchant.split("*")[0].strip() or merchant,
                                     "cats": {}, "rub": 0.0, "checks": [], "excluded": True})
        g["rub"] += s_rub or 0.0
        g["cats"][cat] = g["cats"].get(cat, 0.0) + (s_rub or 0.0)
        g["excluded"] &= bool(excluded)
        if kind == "purchase" and (s_rub or 0) > 0:
            g["checks"].append(s_rub)
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
            "name_ru": name_ru if name_ru and name_ru.lower() != merchant.lower() else None,
            "kzt": round(s_kzt, 2), "rub": round(s_rub, 2) if s_rub is not None else None,
            "orig": abs(_f(orig)) if orig is not None else None, "cur": cur_code,
            "refund": s_kzt < 0, "card": card_, "category": cat, "excluded": bool(excluded),
            "merchant_key": mkey, "merchant_count": m_counts.get(mkey, 1),
        })

    merchants, insights = _merchant_stats(groups)
    return {
        "ok": True,
        "period": period, "from": p_start.isoformat(), "to": p_end.isoformat(),
        "filters": {"card": card or None, "category": category or None, "only_excluded": only_excluded},
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
        "merchants": merchants,
        "insights": insights,
        "last_op_date": last_op.isoformat() if last_op else None,
        "last_upload": last_upload.isoformat() if last_upload else None,
    }


def _merchant_stats(groups):
    """Где больше всего: по каждой сети — сумма, визиты, медианный чек, доля в категории; + выводы.
    Сумма = визиты × чек, поэтому вывод всегда говорит, ЧТО раздуло трату: частота или цена."""
    cat_tot = {}
    out = []
    for g in groups.values():
        cat = max(g["cats"], key=g["cats"].get)            # категория сети — где больше денег
        cat_tot[cat] = cat_tot.get(cat, 0.0) + g["rub"]
        out.append({"key": g["key"], "name": g["name"], "category": cat, "rub": round(g["rub"], 2),
                    "visits": len(g["checks"]), "check": round(median(g["checks"]), 2) if g["checks"] else None,
                    "excluded": g["excluded"], "_checks": g["checks"]})
    out.sort(key=lambda m: -m["rub"])
    for m in out:
        t = cat_tot.get(m["category"]) or 0
        m["share"] = round(m["rub"] / t, 3) if t > 0 else None

    fmt = lambda v: f"{round(v):,}".replace(",", " ")
    times = lambda k: "раз" if k % 10 in (0, 1, 5, 6, 7, 8, 9) or 11 <= k % 100 <= 14 else "раза"
    insights = []
    by_cat = {}
    for m in out:
        if not m["excluded"]:
            by_cat.setdefault(m["category"], []).append(m)
    for cat, ms in sorted(by_cat.items(), key=lambda kv: -cat_tot.get(kv[0], 0)):
        label = CATEGORIES[cat].lower()
        top = ms[0]
        # 1) кто съедает категорию и почему: частота или чек
        if len(ms) >= 2 and top["share"] and top["share"] >= 0.35 and top["visits"] >= MIN_VISITS:
            rest = [c for m in ms[1:] for c in m["_checks"]]
            why = (f"ходим часто ({top['visits']} {times(top['visits'])}), чек обычный ~{fmt(top['check'])} ₽"
                   if rest and top["check"] <= median(rest) * 1.2
                   else f"дорогой чек ~{fmt(top['check'])} ₽, были {top['visits']} {times(top['visits'])}")
            insights.append({"category": cat, "kind": "share",
                             "text": f"{top['name']} — {round(top['share'] * 100)}% трат на {label}: {why}"})
        # 2) дороже за визит — только где чек ≈ цена
        if cat in PRICE_CATS:
            ok = [m for m in ms if m["visits"] >= MIN_VISITS and m["check"]]
            if len(ok) >= 2:
                hi, lo = max(ok, key=lambda m: m["check"]), min(ok, key=lambda m: m["check"])
                k = hi["check"] / lo["check"]
                if k >= 1.5:
                    kt = f"{k:.1f}".removesuffix(".0").replace(".", ",")
                    insights.append({"category": cat, "kind": "price",
                                     "text": f"{hi['name']} дороже {lo['name']} в {kt} раза за визит: "
                                             f"~{fmt(hi['check'])} ₽ против ~{fmt(lo['check'])} ₽"})
    for m in out:
        del m["_checks"]
    return out[:30], insights[:3]


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
    """Правка траты. apply_to_merchant: записать в правило продавца (ключ kaspi_merchant_key, source=manual)
    только переданные поля и снять ручные правки этих полей с его трат — правило действует на все прошлые
    и будущие. Непереданная категория в новом правиле остаётся NULL — её проставит автоматика."""
    if category is not _UNSET and category not in CATEGORIES:
        raise KaspiError("bad_category")
    if excluded is not _UNSET and not isinstance(excluded, bool):
        raise KaspiError("bad_excluded")
    if category is _UNSET and excluded is _UNSET:
        raise KaspiError("nothing_to_update")
    with connection.cursor() as cur:
        cur.execute("SELECT kaspi_merchant_key(merchant, merchant_norm) FROM kaspi_expenses WHERE id = %s", [expense_id])
        row = cur.fetchone()
        if not row:
            raise KaspiError("not_found")
        mnorm = row[0]                         # ключ продавца
        if apply_to_merchant:
            cur.execute("SELECT category, exclude_budget FROM kaspi_merchant_rules WHERE merchant_norm = %s", [mnorm])
            rule = cur.fetchone() or (None, False)
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
            cur.execute(f"UPDATE kaspi_expenses SET {', '.join(sets)} WHERE kaspi_merchant_key(merchant, merchant_norm) = %s",
                        [mnorm])
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

