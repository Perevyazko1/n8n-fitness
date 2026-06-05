"""
JSON-эндпоинты Mini App. Контракты совпадают с прежними n8n-вебхуками
(см. ../n8n-fitness-scan/CLAUDE.md), с двумя уточнениями на реальной БД:
  - delete-food теперь по `id` (а не по номеру строки);
  - food-log/workout-today принимают `date` (backdating без костылей).
Авторизация + CORS — в middleware; здесь уже есть request.tg_user / request.payload.
"""
from datetime import date as date_cls

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from . import calc
from .models import FoodLog, Product, WorkoutCatalog, WorkoutDone, WorkoutLog


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
        meal_type=meal_type_for_hour(now.hour),
    )
    return ok({"ok": True, "message": "добавлено"})


def workout_today(request):
    day = parse_date(request.payload.get("date")) or today()
    return ok(calc.compute_workout_today(request.tg_user, day))


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
    """НОВОЕ: фиксирует, что тренировка за день была → строка в workout_log
    (upsert по user+date). kcal_burned = MET-оценка (позже заменит Apple Watch)."""
    user = request.tg_user
    day = parse_date(request.payload.get("date")) or today()
    exp = calc.expected_today(user, day)
    if exp["type"] != "workout":
        return ok({"ok": False, "error": "rest_day"}, status=400)

    block = exp["number"]
    kcal = round(calc.planned_workout_kcal(user, block))
    duration = sum((r.default_min or 0) for r in WorkoutCatalog.objects.filter(user=user, block_num=block)) or None
    obj, created = WorkoutLog.objects.update_or_create(
        user=user, date=day,
        defaults={"day_plan": exp["label"], "kcal_burned": kcal,
                  "duration_min": duration, "source": "app"},
    )
    return ok({"ok": True, "created": created, "kcal_burned": kcal})


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
