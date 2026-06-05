"""
Разовый импорт Google Sheets → Postgres.

Источник — ОДИН .xlsx-экспорт всей таблицы (в Google Sheets:
File → Download → Microsoft Excel (.xlsx)). Все вкладки в одном файле.

Запуск (контейнер api, файл подмонтировать):
    docker compose run --rm -v "$PWD/export.xlsx:/tmp/export.xlsx" api \
        python manage.py import_sheets /tmp/export.xlsx --wipe

Флаги:
    --wipe      очистить таблицы перед импортом (для повторного прогона)
    --dry-run   только показать, что будет импортировано, без записи
    --telegram-id N   если в листе profile нет chat_id

Идемпотентность: всё в одной транзакции. Логи single-user → привязываются к
TgUser, чей telegram_id = profile.chat_id.
"""
from datetime import date, datetime, time as time_cls

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fitness.models import (
    BodyParams, FoodLog, Product, Profile, TgUser, WalkingLog,
    WorkoutBlock, WorkoutCatalog, WorkoutDone, WorkoutLog,
)


# ---------- коэрсеры ----------
def s(v):
    return "" if v is None else str(v).strip()


def i(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def f(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def to_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    txt = str(v).strip()
    # 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM[:SS]' — берём дату
    txt = txt.split(" ")[0].split("T")[0]
    try:
        return date.fromisoformat(txt)
    except ValueError:
        return None


def to_time(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (datetime, time_cls)):
        return v.strftime("%H:%M")
    txt = str(v).strip()
    # '08:30' или '08:30:00' или '2026-06-02 20:00'
    if " " in txt:
        txt = txt.split(" ")[-1]
    parts = txt.split(":")
    if len(parts) >= 2 and parts[0].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return ""


def to_bool(v):
    return str(v).strip().upper() in ("TRUE", "1", "ДА", "YES")


def rows(ws):
    """Лист → список dict по заголовку первой строки. Пустые строки пропускаем."""
    it = ws.iter_rows(values_only=True)
    try:
        header = [s(h) for h in next(it)]
    except StopIteration:
        return []
    out = []
    for r in it:
        if r is None or all(c in (None, "") for c in r):
            continue
        out.append({header[k]: r[k] for k in range(min(len(header), len(r)))})
    return out


class Command(BaseCommand):
    help = "Импорт Google Sheets (.xlsx) в Postgres"

    def add_arguments(self, parser):
        parser.add_argument("xlsx", help="путь к .xlsx-экспорту таблицы")
        parser.add_argument("--wipe", action="store_true", help="очистить таблицы перед импортом")
        parser.add_argument("--dry-run", action="store_true", help="без записи в БД")
        parser.add_argument("--telegram-id", type=int, default=None,
                            help="telegram_id юзера, если в profile нет chat_id")

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("Нужен openpyxl: pip install openpyxl (или добавлен в requirements.txt)")

        wb = openpyxl.load_workbook(opts["xlsx"], data_only=True, read_only=True)
        sheets = {ws.title: ws for ws in wb.worksheets}
        self.stdout.write(f"Вкладки в файле: {', '.join(sheets)}")

        def sheet(name):
            ws = sheets.get(name)
            return rows(ws) if ws else []

        # --- определяем юзера по profile.chat_id ---
        profile_rows = sheet("profile")
        chat_id = opts["telegram_id"]
        if profile_rows and not chat_id:
            chat_id = i(profile_rows[0].get("chat_id"))
        if not chat_id:
            raise CommandError("Не найден chat_id (лист profile пуст?) — передай --telegram-id")

        report = {}
        dry = opts["dry_run"]

        try:
            with transaction.atomic():
                if opts["wipe"] and not dry:
                    for M in (FoodLog, WorkoutLog, WorkoutDone, WalkingLog, BodyParams,
                              Product, WorkoutCatalog, WorkoutBlock, Profile, TgUser):
                        M.objects.all().delete()

                user, _ = TgUser.objects.get_or_create(
                    telegram_id=chat_id,
                    defaults={"first_name": s(profile_rows[0].get("first_name", "")) if profile_rows else ""},
                )

                # profile (1 строка)
                if profile_rows:
                    p = profile_rows[0]
                    Profile.objects.update_or_create(user=user, defaults=dict(
                        height_cm=f(p.get("height_cm")), weight_kg=f(p.get("weight_kg")),
                        age=i(p.get("age")), sex=s(p.get("sex")),
                        activity_level=s(p.get("activity_level")), goal=s(p.get("goal")) or "maintain",
                        daily_baseline_kcal=i(p.get("daily_baseline_kcal")), bmr=i(p.get("bmr")),
                        training_days_interval=i(p.get("training_days_interval")),
                        target_kcal=i(p.get("target_kcal")),
                        target_protein_g=f(p.get("target_protein_g")),
                        target_fat_g=f(p.get("target_fat_g")),
                        target_carbs_g=f(p.get("target_carbs_g")),
                    ))
                    report["profile"] = 1

                # food_log
                n = 0
                for r in sheet("food_log"):
                    d = to_date(r.get("date"))
                    if not d:
                        continue
                    FoodLog.objects.create(
                        user=user, date=d, time=to_time(r.get("time")),
                        description=s(r.get("description")),
                        kcal=i(r.get("kcal")) or 0, protein=f(r.get("protein")) or 0,
                        fat=f(r.get("fat")) or 0, carbs=f(r.get("carbs")) or 0,
                        meal_type=s(r.get("meal_type")))
                    n += 1
                report["food_log"] = n

                # workout_log (uniq user+date)
                n = 0
                for r in sheet("workout_log"):
                    d = to_date(r.get("date"))
                    if not d:
                        continue
                    WorkoutLog.objects.update_or_create(user=user, date=d, defaults=dict(
                        day_plan=s(r.get("day_plan")), exercises_done=s(r.get("exercises_done")),
                        duration_min=i(r.get("duration_min")), kcal_burned=i(r.get("kcal_burned")),
                        notes=s(r.get("notes")), source="sheets"))
                    n += 1
                report["workout_log"] = n

                # workout_done (может не быть вкладки)
                n = 0
                for r in sheet("workout_done"):
                    d = to_date(r.get("date"))
                    bn = i(r.get("block_num"))
                    ex = s(r.get("exercise"))
                    if not d or not bn or not ex:
                        continue
                    WorkoutDone.objects.update_or_create(
                        user=user, date=d, block_num=bn, exercise=ex,
                        defaults={"done": to_bool(r.get("done"))})
                    n += 1
                report["workout_done"] = n

                # walking_log
                n = 0
                for r in sheet("walking_log"):
                    d = to_date(r.get("date"))
                    if not d:
                        continue
                    WalkingLog.objects.create(
                        user=user, date=d, time=to_time(r.get("time")),
                        activity=s(r.get("activity")), duration_min=i(r.get("duration_min")),
                        distance_km=f(r.get("distance_km")), speed_kmh=f(r.get("speed_kmh")),
                        kcal_burned=i(r.get("kcal_burned")), notes=s(r.get("notes")))
                    n += 1
                report["walking_log"] = n

                # body_params
                n = 0
                for r in sheet("body_params"):
                    d = to_date(r.get("date"))
                    if not d:
                        continue
                    BodyParams.objects.create(
                        user=user, date=d, weight=f(r.get("weight")),
                        body_fat_pct=f(r.get("body_fat_pct")), notes=s(r.get("notes")))
                    n += 1
                report["body_params"] = n

                # products (глобальные, по barcode)
                n = 0
                for r in sheet("products"):
                    bc = s(r.get("barcode"))
                    if not bc:
                        continue
                    Product.objects.update_or_create(barcode=bc, defaults=dict(
                        name=s(r.get("name")), aliases=s(r.get("aliases")),
                        kcal_per_100g=f(r.get("kcal_per_100g")), protein_per_100g=f(r.get("protein_per_100g")),
                        fat_per_100g=f(r.get("fat_per_100g")), carbs_per_100g=f(r.get("carbs_per_100g")),
                        default_serving_g=i(r.get("default_serving_g")), notes=s(r.get("notes"))))
                    n += 1
                report["products"] = n

                # workouts_flat → WorkoutCatalog
                n = 0
                for r in sheet("workouts_flat"):
                    ex = s(r.get("exercise"))
                    bn = i(r.get("block_num"))
                    if not ex or not bn:
                        continue
                    WorkoutCatalog.objects.create(
                        user=user, block_num=bn, group=s(r.get("group")), exercise=ex,
                        sets=s(r.get("sets")), reps=s(r.get("reps")), weight=s(r.get("weight")),
                        note=s(r.get("note")), met=f(r.get("met")), default_min=i(r.get("default_min")))
                    n += 1
                report["workouts_flat"] = n

                # workout_blocks (uniq user+block_num)
                n = 0
                for r in sheet("workout_blocks"):
                    bn = i(r.get("block_num"))
                    if not bn:
                        continue
                    WorkoutBlock.objects.update_or_create(
                        user=user, block_num=bn,
                        defaults={"label": s(r.get("label")), "active": to_bool(r.get("active"))})
                    n += 1
                report["workout_blocks"] = n

                if dry:
                    transaction.set_rollback(True)
        except Exception as e:
            raise CommandError(f"Импорт упал, откат: {e}")

        self.stdout.write(self.style.SUCCESS(
            ("[DRY-RUN] " if dry else "") + f"Импорт для telegram_id={chat_id}:"))
        for k, v in report.items():
            self.stdout.write(f"  {k}: {v}")
