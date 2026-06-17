"""
JSON-эндпоинты Mini App. Контракты совпадают с прежними n8n-вебхуками
(см. ../n8n-fitness-scan/CLAUDE.md), с двумя уточнениями на реальной БД:
  - delete-food теперь по `id` (а не по номеру строки);
  - food-log/workout-today принимают `date` (backdating без костылей).
Авторизация + CORS — в middleware; здесь уже есть request.tg_user / request.payload.
"""
import hashlib
import json
from datetime import date as date_cls
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from . import calc, streak
from .models import (
    BodyParams, FoodLog, Product, Profile, WalkingLog, WorkoutBlock,
    WorkoutCatalog, WorkoutDone, WorkoutLog,
)


def _f(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _i(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


# ---------- helpers ----------
def today():
    return timezone.localdate()


def now_hm():
    return timezone.localtime().strftime("%H:%M")


def meal_type_for_hour(h):
    if h < 11:
        return "завтрак"
    if h < 16:
        return "обед"
    if h < 19:
        return "перекус"
    return "ужин"


def parse_date(s):
    try:
        return date_cls.fromisoformat(s) if isinstance(s, str) else None
    except ValueError:
        return None


def ok(data, status=200):
    return JsonResponse(data, status=status)


# ---------- endpoints ----------
def health(request):
    return ok({"ok": True, "service": "fitness-api"})


def dashboard(request):
    return ok(calc.compute_dashboard(request.tg_user, today()))


def food_log(request):
    user = request.tg_user
    day = parse_date(request.payload.get("date")) or today()
    items = []
    for f in FoodLog.objects.filter(user=user, date=day).order_by("time", "id"):
        items.append({
            "id": f.id, "time": f.time or "", "description": f.description or "",
            "kcal": int(f.kcal or 0), "protein": calc.r1(f.protein),
            "fat": calc.r1(f.fat), "carbs": calc.r1(f.carbs),
            "meal_type": f.meal_type or "",
        })
    s = {"kcal": round(sum(i["kcal"] for i in items)),
         "protein": calc.r1(sum(i["protein"] for i in items)),
         "fat": calc.r1(sum(i["fat"] for i in items)),
         "carbs": calc.r1(sum(i["carbs"] for i in items))}
    return ok({"ok": True, "date": day.isoformat(), "items": items, "sum": s})


def delete_food(request):
    user = request.tg_user
    fid = request.payload.get("id")
    deleted, _ = FoodLog.objects.filter(user=user, id=fid).delete()
    if not deleted:
        return ok({"ok": False, "error": "not_found"}, status=404)
    return ok({"ok": True})


def update_food(request):
    """Точечное изменение записи дневника (пока — только приём пищи)."""
    user = request.tg_user
    p = request.payload
    fid = p.get("id")
    fields = {}
    mt = p.get("meal_type")
    if mt is not None:
        fields["meal_type"] = str(mt)[:32]
    if not fields:
        return ok({"ok": False, "error": "nothing_to_update"}, status=400)
    updated = FoodLog.objects.filter(user=user, id=fid).update(**fields)
    if not updated:
        return ok({"ok": False, "error": "not_found"}, status=404)
    return ok({"ok": True})


def repeat_food(request):
    user = request.tg_user
    p = request.payload
    day = parse_date(p.get("date")) or today()  # по умолчанию — сегодня
    now = timezone.localtime()
    FoodLog.objects.create(
        user=user, date=day, time=now.strftime("%H:%M"),
        description=p.get("description", "") or "",
        kcal=round(float(p.get("kcal") or 0)),
        protein=float(p.get("protein") or 0),
        fat=float(p.get("fat") or 0),
        carbs=float(p.get("carbs") or 0),
        meal_type=(str(p.get("meal_type"))[:32] if p.get("meal_type") else meal_type_for_hour(now.hour)),
    )
    return ok({"ok": True, "message": "добавлено"})


def workout_today(request):
    day = parse_date(request.payload.get("date")) or today()
    raw_block = request.payload.get("block")
    forced_block = int(raw_block) if raw_block else None
    return ok(calc.compute_workout(request.tg_user, day, forced_block))


def toggle_exercise(request):
    user = request.tg_user
    p = request.payload
    day = parse_date(p.get("date")) or today()
    block = int(p.get("block_num") or 0)
    exercise = (p.get("exercise") or "").strip()
    if not block or not exercise:
        return ok({"ok": False, "error": "missing_fields"}, status=400)
    done = p.get("done") is True or str(p.get("done")).upper() == "TRUE"
    WorkoutDone.objects.update_or_create(
        user=user, date=day, block_num=block, exercise=exercise,
        defaults={"done": done},
    )
    return ok({"ok": True})


def complete_workout(request):
    """Фиксирует тренировку за день → строка в workout_log (upsert по user+date).
    Блок берём из payload (выбранный на странице), иначе — ожидаемый для сегодня.
    Работает и задним числом. kcal_burned считается ТОЛЬКО по ВЫПОЛНЕННЫМ
    (отмеченным) упражнениям — done_workout_stats (позже заменит Apple Watch)."""
    user = request.tg_user
    p = request.payload
    day = parse_date(p.get("date")) or today()
    raw = p.get("block")
    block = int(raw) if raw else None
    if not block:
        exp = calc.expected_today(user, day)
        if exp["type"] != "workout":
            return ok({"ok": False, "error": "no_block"}, status=400)
        block = exp["number"]

    label = next((b["label"] for b in calc.active_blocks_list(user)
                  if b["block_num"] == block), f"№{block}")
    kcal_auto, duration = calc.done_workout_stats(user, day, block)
    # ручной приоритет: если юзер задал расход — берём его
    override = _i(p.get("kcal_burned"))
    kcal = override if override is not None else kcal_auto
    obj, created = WorkoutLog.objects.update_or_create(
        user=user, date=day,
        defaults={"day_plan": label, "kcal_burned": kcal,
                  "duration_min": duration, "source": "app"},
    )
    return ok({"ok": True, "created": created, "kcal_burned": kcal})


def uncomplete_workout(request):
    """Отменить подтверждение тренировки за день → удалить строку workout_log.
    Расход тренировки уходит из бюджета (лимит уменьшается). Галочки упражнений
    (workout_done) НЕ трогаем — можно перевыполнить и подтвердить заново."""
    user = request.tg_user
    day = parse_date(request.payload.get("date")) or today()
    deleted, _ = WorkoutLog.objects.filter(user=user, date=day).delete()
    return ok({"ok": True, "deleted": bool(deleted)})


# ---------- cron (серверные, токен-авторизация в middleware) ----------
def cron_meal_reminders(request):
    """Напоминания о еде: window=afternoon|evening. Возвращает сообщения для рассылки."""
    p = request.payload
    window = p.get("window") or "afternoon"
    day = parse_date(p.get("date")) or today()
    msgs = streak.meal_reminders(window, day)
    return ok({"ok": True, "window": window, "messages": msgs})


def cron_evaluate_day(request):
    """Вечерняя оценка дня по всем юзерам: двигает серии, возвращает сообщения (вехи/заморозки/сбросы)."""
    day = parse_date(request.payload.get("date")) or today()
    msgs = streak.evaluate_all(day)
    return ok({"ok": True, "date": day.isoformat(), "messages": msgs})


def profile(request):
    """Профиль для настроек: редактируемые параметры тела + посчитанные КБЖУ (read-only).
    `complete` — заполнены ли обязательные поля и посчитан target_kcal (для онбординга)."""
    p = getattr(request.tg_user, "profile", None)
    if not p:
        return ok({"ok": True, "exists": False, "complete": False})
    complete = all([
        p.height_cm, p.weight_kg, p.age, p.sex,
        p.activity_level, p.goal, p.target_kcal,
    ])
    return ok({
        "ok": True, "exists": True, "complete": bool(complete),
        "height_cm": p.height_cm, "weight_kg": p.weight_kg, "age": p.age,
        "sex": p.sex or "m", "activity_level": p.activity_level or "moderate",
        "goal": p.goal or "maintain", "training_days_interval": p.training_days_interval,
        "body_fat_pct": calc.latest_body_fat(p),
        "bmr": p.bmr, "daily_baseline_kcal": p.daily_baseline_kcal,
        "target_kcal": p.target_kcal, "target_protein_g": p.target_protein_g,
        "target_fat_g": p.target_fat_g, "target_carbs_g": p.target_carbs_g,
    })


def profile_save(request):
    """Сохранить параметры тела. КБЖУ обычно через пересчёт, но можно задать вручную
    (режим «Считать автоматически» выкл) — тогда передаются target_*. % жира пишем
    отдельным замером в BodyParams (для будущего графика динамики)."""
    p = request.payload
    prof, _ = Profile.objects.get_or_create(user=request.tg_user)
    prof.height_cm = _f(p.get("height_cm"))
    prof.weight_kg = _f(p.get("weight_kg"))
    prof.age = _i(p.get("age"))
    if p.get("sex"):
        prof.sex = str(p.get("sex")).strip()
    if p.get("activity_level"):
        prof.activity_level = str(p.get("activity_level")).strip()
    if p.get("goal"):
        prof.goal = str(p.get("goal")).strip()
    if p.get("training_days_interval") is not None:
        prof.training_days_interval = _i(p.get("training_days_interval"))
    # ручные цели КБЖУ (если переданы)
    if p.get("target_kcal") not in (None, ""):
        prof.target_kcal = _i(p.get("target_kcal"))
        prof.target_protein_g = _f(p.get("target_protein_g"))
        prof.target_fat_g = _f(p.get("target_fat_g"))
        prof.target_carbs_g = _f(p.get("target_carbs_g"))
    prof.save()
    # % жира → замер на сегодня
    bf = _f(p.get("body_fat_pct"))
    if bf is not None:
        bp = BodyParams.objects.filter(user=request.tg_user, date=today()).order_by("-id").first()
        if bp:
            bp.body_fat_pct = bf
            bp.weight = prof.weight_kg
            bp.save()
        else:
            BodyParams.objects.create(user=request.tg_user, date=today(),
                                      body_fat_pct=bf, weight=prof.weight_kg)
    return ok({"ok": True})


def profile_recalc(request):
    """Пересчитать КБЖУ из текущих параметров тела (Mifflin) и сохранить."""
    prof = getattr(request.tg_user, "profile", None)
    if not prof:
        return ok({"ok": False, "error": "no_profile"}, status=400)
    upd = calc.recalc_targets(prof)
    for k, v in upd.items():
        setattr(prof, k, v)
    prof.save()
    return ok({"ok": True, **upd})


def products(request):
    """Справочник продуктов (что бот «знает»). Просмотр."""
    items = []
    for p in Product.objects.all().order_by("name"):
        items.append({
            "id": p.id, "name": p.name, "aliases": p.aliases or "",
            "kcal_per_100g": p.kcal_per_100g, "protein_per_100g": p.protein_per_100g,
            "fat_per_100g": p.fat_per_100g, "carbs_per_100g": p.carbs_per_100g,
            "default_serving_g": p.default_serving_g, "barcode": p.barcode or "",
        })
    return ok({"ok": True, "items": items})


def save_product(request):
    """Сохранить/обновить продукт в справочнике (upsert по имени через синтетический barcode)."""
    p = request.payload
    name = (p.get("name") or "").strip()
    if not name:
        return ok({"ok": False, "error": "no_name"}, status=400)
    barcode = (p.get("barcode") or "").strip()
    if not barcode:
        barcode = ("man-" + hashlib.md5(name.lower().encode()).hexdigest())[:32]
    Product.objects.update_or_create(
        barcode=barcode,
        defaults={
            "name": name,
            "aliases": p.get("aliases", "") or "",
            "kcal_per_100g": _f(p.get("kcal_per_100g")),
            "protein_per_100g": _f(p.get("protein_per_100g")),
            "fat_per_100g": _f(p.get("fat_per_100g")),
            "carbs_per_100g": _f(p.get("carbs_per_100g")),
            "default_serving_g": _i(p.get("default_serving_g")),
            "notes": p.get("notes", "") or "из приложения",
        },
    )
    return ok({"ok": True, "message": "добавлено в продукты"})


# ---------- поиск продуктов в Open Food Facts (прокси) ----------
# Фронт раньше ходил в OFF напрямую, но из браузера это бьётся о CORS и частые
# 503 у cgi/search.pl. Делаем серверный прокси: ходим в OFF отсюда (CORS не нужен,
# можно слать User-Agent → меньше троттлинга) и отдаём фронту готовый JSON в той же
# форме, что и /products (name + *_per_100g + default_serving_g).
_OFF_UA = "RyzhFitness/1.0 (Telegram Mini App; +https://n8n-fitness.ru)"


def _off_get(url, timeout=8):
    req = Request(url, headers={"User-Agent": _OFF_UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _off_norm(name, brands, code, n, serving):
    """OFF-запись → продукт фронта (на 100г). None, если нельзя залогировать."""
    n = n or {}
    kcal = _f(n.get("energy-kcal_100g"))
    name = name.strip() if isinstance(name, str) else ""
    if kcal is None or not name:
        return None
    if isinstance(brands, list):
        brand = (brands[0] if brands else "") or ""
    else:
        brand = str(brands or "").split(",")[0]
    return {
        "name": name,
        "brand": str(brand).strip(),
        "barcode": code or "",
        "kcal_per_100g": calc.r1(kcal),
        "protein_per_100g": calc.r1(_f(n.get("proteins_100g"))),
        "fat_per_100g": calc.r1(_f(n.get("fat_100g"))),
        "carbs_per_100g": calc.r1(_f(n.get("carbohydrates_100g"))),
        "default_serving_g": _i(serving) or 100,
    }


def product_search(request):
    q = (request.payload.get("q") or "").strip()
    if len(q) < 2:
        return ok({"ok": True, "items": []})
    fields = "code,product_name,brands,nutriments,serving_quantity"
    items = []

    # 1) быстрый индекс Search-a-licious (server-side — без проблемы CORS).
    try:
        data = _off_get(
            "https://search.openfoodfacts.org/search?q=" + quote(q)
            + "&page_size=24&fields=" + fields
        )
        for h in (data.get("hits") or []):
            it = _off_norm(h.get("product_name"), h.get("brands"), h.get("code"),
                           h.get("nutriments"), h.get("serving_quantity"))
            if it:
                items.append(it)
    except Exception:
        items = []

    # 2) фолбэк на классический cgi-поиск, если индекс молчит/пуст.
    if not items:
        try:
            data = _off_get(
                "https://world.openfoodfacts.org/cgi/search.pl?search_terms=" + quote(q)
                + "&search_simple=1&action=process&json=1&page_size=24&fields=" + fields,
                timeout=12,
            )
            for p in (data.get("products") or []):
                it = _off_norm(p.get("product_name"), p.get("brands"), p.get("code"),
                               p.get("nutriments"), p.get("serving_quantity"))
                if it:
                    items.append(it)
        except Exception:
            pass

    return ok({"ok": True, "items": items[:24]})


def exercise_save(request):
    """Создать/обновить упражнение в плане (WorkoutCatalog). id → апдейт, иначе создание."""
    user = request.tg_user
    p = request.payload
    name = (p.get("exercise") or "").strip()
    block = _i(p.get("block_num"))
    if not name or not block:
        return ok({"ok": False, "error": "missing"}, status=400)
    group = (p.get("group") or "").strip()
    # MET и длительность: если юзер не задал — прикидываем по категории (иначе расход 0)
    met = _f(p.get("met"))
    dmin = _i(p.get("default_min"))
    if met is None or dmin is None:
        est_met, est_min = calc.estimate_met(group, name)
        met = est_met if met is None else met
        dmin = est_min if dmin is None else dmin
    fields = {
        "block_num": block,
        "group": group,
        "exercise": name,
        "sets": str(p.get("sets") or "").strip(),
        "reps": str(p.get("reps") or "").strip(),
        "weight": str(p.get("weight") or "").strip(),
        "note": (p.get("note") or "").strip(),
        "met": met,
        "default_min": dmin,
    }
    # ручной расход за упражнение: ключ передан → пишем (число или null=сброс к авто);
    # ключа нет → поле не трогаем (обратная совместимость со старым фронтом).
    if "kcal" in p:
        fields["kcal_override"] = _i(p.get("kcal"))
    ex_id = _i(p.get("id"))
    if ex_id:
        WorkoutCatalog.objects.filter(user=user, id=ex_id).update(**fields)
    else:
        WorkoutCatalog.objects.create(user=user, **fields)
    return ok({"ok": True})


def exercise_delete(request):
    user = request.tg_user
    eid = _i(request.payload.get("id"))
    deleted, _ = WorkoutCatalog.objects.filter(user=user, id=eid).delete()
    return ok({"ok": bool(deleted)})


def block_save(request):
    """Создать/переименовать блок плана (WorkoutBlock, upsert по user+block_num).
    Без block_num — создаётся следующий по номеру. active — вкл/выкл блока."""
    user = request.tg_user
    p = request.payload
    bn = _i(p.get("block_num"))
    if not bn:
        existing = list(WorkoutBlock.objects.filter(user=user).values_list("block_num", flat=True))
        bn = (max(existing) + 1) if existing else 1
    defaults = {"label": (p.get("label") or f"№{bn}").strip()}
    if p.get("active") is not None:
        defaults["active"] = bool(p.get("active"))
    WorkoutBlock.objects.update_or_create(user=user, block_num=bn, defaults=defaults)
    return ok({"ok": True, "block_num": bn})


def block_delete(request):
    """Удалить блок и все его упражнения."""
    user = request.tg_user
    bn = _i(request.payload.get("block_num"))
    if not bn:
        return ok({"ok": False, "error": "no_block"}, status=400)
    WorkoutCatalog.objects.filter(user=user, block_num=bn).delete()
    WorkoutBlock.objects.filter(user=user, block_num=bn).delete()
    return ok({"ok": True})


def log_walking(request):
    """Дневная ходьба из приложения: км + темп → нет-MET расход. Upsert по (user, date).
    Общий потолок дневной цели (1.4×) в compute_dashboard не даёт лимиту раздуться."""
    user = request.tg_user
    p = request.payload
    day = parse_date(p.get("date")) or today()
    km = _f(p.get("km")) or 0
    pace = (p.get("pace") or "brisk").strip()
    if km <= 0:
        # км=0 → отмена ходьбы за день
        WalkingLog.objects.filter(user=user, date=day, source="app").delete()
        return ok({"ok": True, "kcal_burned": 0, "km": 0})
    profile = getattr(user, "profile", None)
    weight = (profile.weight_kg if profile else None) or 76
    kcal = calc.walk_kcal(weight, km, pace)
    speed = calc.WALK_PACE.get(pace, calc.WALK_PACE["brisk"])[0]
    minutes = round(km / speed * 60) if speed else None
    WalkingLog.objects.update_or_create(
        user=user, date=day, source="app",
        defaults={"activity": "ходьба", "distance_km": km, "speed_kmh": speed,
                  "duration_min": minutes, "kcal_burned": kcal,
                  "time": timezone.localtime().strftime("%H:%M")},
    )
    return ok({"ok": True, "kcal_burned": kcal, "km": km})


def walking(request):
    """Ходьба за день для UI: запись приложения + общий итог дня."""
    user = request.tg_user
    day = parse_date(request.payload.get("date")) or today()
    row = WalkingLog.objects.filter(user=user, date=day, source="app").order_by("-id").first()
    total = sum((w.kcal_burned or 0) for w in WalkingLog.objects.filter(user=user, date=day))
    return ok({
        "ok": True, "date": day.isoformat(),
        "km": (row.distance_km if row else 0) or 0,
        "pace": calc.pace_from_speed(row.speed_kmh) if row else "brisk",
        "kcal_burned": (row.kcal_burned if row else 0) or 0,
        "day_total_kcal": round(total),
    })


def scan_barcode(request):
    """Логирование по штрихкоду из сканера: action=log_food | add_product."""
    user = request.tg_user
    p = request.payload
    action = p.get("action")
    if action == "log_food":
        now = timezone.localtime()
        FoodLog.objects.create(
            user=user, date=today(), time=now.strftime("%H:%M"),
            description=p.get("description", "") or "",
            kcal=round(float(p.get("kcal") or 0)),
            protein=float(p.get("protein") or 0),
            fat=float(p.get("fat") or 0),
            carbs=float(p.get("carbs") or 0),
            meal_type=meal_type_for_hour(now.hour),
        )
        return ok({"ok": True, "message": "записал"})
    if action == "add_product":
        with transaction.atomic():
            Product.objects.update_or_create(
                barcode=str(p.get("barcode") or "").strip(),
                defaults={
                    "name": p.get("name", "") or "",
                    "aliases": p.get("aliases", "") or "",
                    "kcal_per_100g": p.get("kcal_per_100g"),
                    "protein_per_100g": p.get("protein_per_100g"),
                    "fat_per_100g": p.get("fat_per_100g"),
                    "carbs_per_100g": p.get("carbs_per_100g"),
                    "default_serving_g": p.get("default_serving_g"),
                    "notes": p.get("notes", "") or "",
                },
            )
        return ok({"ok": True, "message": "продукт сохранён"})
    return ok({"ok": False, "error": "unknown_action"}, status=400)
