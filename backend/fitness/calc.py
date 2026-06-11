"""
Расчётный сервис — порт логики из n8n (`Build Context` / `Compute Dashboard` /
`Compute Workout Today`). ЕДИНОЕ место вместо трёх дублей.
Никакого LLM — чистая детерминированная математика.
"""
import re

from .models import (
    BodyParams, FoodLog, Streak, WalkingLog, WorkoutBlock, WorkoutCatalog, WorkoutDone, WorkoutLog,
)

# Лис стартует НЕЙТРАЛЬНЫМ (тамагочи: к телу юзера не привязываем — форма растёт/тает
# только от режима). 50 = середина шкалы 0..100.
NEUTRAL_START = 50


def latest_body_fat(profile):
    """Последний заполненный замер % жира пользователя (или None).
    К лису НЕ привязан — пригодится для будущего графика динамики веса/жира."""
    if profile is None or getattr(profile, "user_id", None) is None:
        return None
    row = (BodyParams.objects
           .filter(user_id=profile.user_id, body_fat_pct__isnull=False)
           .order_by("-date", "-id").first())
    return row.body_fat_pct if row else None


GOAL_MULT = {"lose": 0.8, "maintain": 1.0, "gain": 1.15}
# «Фон» (NEAT) — бытовая активность сверх BMR, БЕЗ спорта. Зависит от образа жизни.
# Логированные ходьба/тренировки идут отдельно сверху (в дашборде/Build Context).
ACT_BASELINE = {"sedentary": 150, "light": 250, "moderate": 350, "active": 500, "very": 650}


def recalc_targets(profile):
    """ЕДИНАЯ динамическая модель: bmr (Mifflin), фон от активности, и БАЗОВАЯ дневная
    цель (день без логированной активности) = clamp((bmr+фон)×goal). На дашборде сверху
    добавляются реальные ходьба/тренировки. Возвращает dict полей для сохранения."""
    sex = "f" if str(profile.sex or "m").lower()[:1] in ("f", "ж") else "m"
    h = profile.height_cm or 0
    w = profile.weight_kg or 0
    a = profile.age or 0
    baseline = ACT_BASELINE.get(str(profile.activity_level or "moderate").lower(), 350)
    gmult = GOAL_MULT.get(str(profile.goal or "maintain").lower(), 1.0)
    bmr = round(10 * w + 6.25 * h - 5 * a + (5 if sex == "m" else -161))
    floor = round(bmr * 1.1)
    ref = max(floor, round((bmr + baseline) * gmult))   # базовая цель (rest day), как в compute_dashboard
    tp = round(w * 1.8)
    tf = round(w * 1.0)
    tc = max(0, round((ref - tp * 4 - tf * 9) / 4))
    return {
        "bmr": bmr,
        "daily_baseline_kcal": baseline,
        "target_kcal": ref,
        "target_protein_g": tp,
        "target_fat_g": tf,
        "target_carbs_g": tc,
    }


def r1(x):
    return round((float(x) if x is not None else 0.0) * 10) / 10


# ===== Маскот-лис: счётчик 0..100 → тир тела =====
def initial_score(profile, kind):
    """Старт лисёнка — НЕЙТРАЛЬ для обеих осей (тамагочи: к телу юзера не привязываем).
    Дальше живот/мышцы двигаются только от режима (питание/тренировки)."""
    return NEUTRAL_START


def muscle_tier(score):
    s = 50 if score is None else score
    if s < 25:
        return 0
    if s < 50:
        return 1
    if s < 75:
        return 2
    return 3


def belly_tier(score):
    # высокий счёт питания = плоский живот (B0), низкий = пузо (B3)
    s = 50 if score is None else score
    if s >= 75:
        return 0
    if s >= 50:
        return 1
    if s >= 25:
        return 2
    return 3


def parse_workout_number(plan):
    if not plan:
        return None
    m = re.search(r"№?\s*([1-4])", str(plan))
    if m:
        return int(m.group(1))
    s = str(plan).lower()
    if "грудь" in s and "бицепс" in s:
        return 1
    if "плечи" in s and "грудь" in s:
        return 2
    if "спина" in s and "трицепс" in s:
        return 3
    if "ноги" in s:
        return 4
    return None


def blocks_state(user):
    state = {}
    for r in WorkoutBlock.objects.filter(user=user):
        if not r.block_num:
            continue
        state[r.block_num] = {"label": r.label or f"№{r.block_num}", "active": bool(r.active)}
    if not state:
        # нет явных блоков — выводим из плана (какие block_num есть в упражнениях).
        # У нового юзера упражнений нет → пусто, он создаёт план сам.
        nums = sorted({n for n in WorkoutCatalog.objects.filter(user=user)
                       .exclude(exercise="").values_list("block_num", flat=True) if n})
        for n in nums:
            state[n] = {"label": f"№{n}", "active": True}
    return state


def expected_today(user, day):
    """{'type':'workout','number','label'} | {'type':'rest','days_until_next'}"""
    profile = getattr(user, "profile", None)
    interval = (profile.training_days_interval if profile else None) or 1

    last = WorkoutLog.objects.filter(user=user).order_by("date").last()
    state = blocks_state(user)
    active = sorted(n for n, v in state.items() if v["active"])

    def next_active_after(last_n):
        if not active:
            return None
        after = next((n for n in active if n > last_n), None)
        return after if after is not None else active[0]

    if not active:
        return {"type": "rest", "days_until_next": None}
    if not last:
        n = active[0]
        return {"type": "workout", "number": n, "label": state[n]["label"]}

    days_since = (day - last.date).days
    if days_since < interval:
        return {"type": "rest", "days_until_next": interval - days_since}
    last_n = parse_workout_number(last.day_plan) or 0
    next_n = next_active_after(last_n)
    return {"type": "workout", "number": next_n, "label": state[next_n]["label"]}


def _food_sum(user, day):
    agg = {"kcal": 0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    for f in FoodLog.objects.filter(user=user, date=day):
        agg["kcal"] += f.kcal or 0
        agg["protein"] += f.protein or 0
        agg["fat"] += f.fat or 0
        agg["carbs"] += f.carbs or 0
    agg["kcal"] = round(agg["kcal"])
    agg["protein"] = r1(agg["protein"])
    agg["fat"] = r1(agg["fat"])
    agg["carbs"] = r1(agg["carbs"])
    return agg


def planned_workout_kcal(user, block_num):
    profile = getattr(user, "profile", None)
    weight = (profile.weight_kg if profile else None) or 76
    total = 0.0
    for r in WorkoutCatalog.objects.filter(user=user, block_num=block_num):
        if not r.exercise:
            continue
        if r.met and r.default_min:
            total += r.met * weight * r.default_min / 60
    return total


# MET и типовая длительность (мин) по категории упражнения (по ключевым словам).
# Нужно, чтобы у созданных в приложении упражнений был ненулевой расход.
MET_BY_GROUP = [
    (("разм", "warm"), (3.5, 10)),
    (("кардио", "cardio", "бег", "велотр", "велосип", "эллипс", "скакал", "гребл"), (7.0, 20)),
    (("кор", "пресс", "core", "планк", "abs"), (4.0, 6)),
    (("замин", "растяж", "стрет", "cool", "stretch", "йог"), (2.5, 6)),
    (("силов", "жим", "тяга", "присед", "становая", "штанг", "гантел", "подтяг", "отжим", "strength"), (5.0, 6)),
]
DEFAULT_MET = (4.0, 6)


# Темп ходьбы → (скорость км/ч, MET). Расход считаем по НЕТ-MET (MET−1):
# вычитаем BMR, который уже учтён в дневной цели — чтобы не завышать лимит.
WALK_PACE = {
    "stroll": (4.0, 2.8),   # прогулочный
    "brisk":  (5.5, 3.5),   # бодрый
    "fast":   (6.5, 4.3),   # быстрый
    "jog":    (8.5, 6.0),   # бег трусцой
}


def walk_kcal(weight, km, pace="brisk"):
    """Консервативный нет-MET расход ходьбы: (MET−1) × вес × минуты/60."""
    speed, met = WALK_PACE.get(str(pace or "brisk"), WALK_PACE["brisk"])
    km = max(0.0, float(km or 0))
    if km <= 0 or speed <= 0:
        return 0
    minutes = km / speed * 60.0
    net = max(met - 1.0, 0.0)
    return round(net * (float(weight) if weight else 76) * minutes / 60.0)


def pace_from_speed(speed):
    for name, (sp, _met) in WALK_PACE.items():
        if abs((float(speed) if speed else 0) - sp) < 0.1:
            return name
    return "brisk"


def estimate_met(group, exercise=""):
    """Прикидка (MET, минуты) по категории/названию упражнения."""
    s = (str(group or "") + " " + str(exercise or "")).lower()
    for keys, val in MET_BY_GROUP:
        if any(k in s for k in keys):
            return val
    return DEFAULT_MET


def exercise_auto_kcal(row, weight):
    """Авто-оценка расхода за упражнение по MET-формуле (без ручного override)."""
    if row.met and row.default_min:
        return round(row.met * weight * row.default_min / 60)
    return 0


def done_workout_stats(user, day, block):
    """Расход и длительность ТОЛЬКО по выполненным (отмеченным) упражнениям блока.
    За упражнение берём ручной kcal_override, если задан, иначе авто по MET-формуле."""
    profile = getattr(user, "profile", None)
    weight = (profile.weight_kg if profile else None) or 76
    done = {
        d.exercise.strip()
        for d in WorkoutDone.objects.filter(user=user, date=day, block_num=block, done=True)
    }
    kcal = 0.0
    minutes = 0
    for r in WorkoutCatalog.objects.filter(user=user, block_num=block):
        if not r.exercise or r.exercise.strip() not in done:
            continue
        if r.kcal_override is not None:        # ручной расход за упражнение — приоритет
            kcal += r.kcal_override
        else:                                  # иначе авто по MET-формуле
            kcal += exercise_auto_kcal(r, weight)
        minutes += (r.default_min or 0)
    return round(kcal), (minutes or None)


def compute_dashboard(user, day):
    profile = getattr(user, "profile", None)
    if not profile:
        return {"ok": False, "error": "no_profile", "date": day.isoformat()}

    today_sum = _food_sum(user, day)
    exp = expected_today(user, day)

    bmr = profile.bmr or 1600
    baseline = profile.daily_baseline_kcal or 280
    goal = (profile.goal or "maintain").lower()
    mult = GOAL_MULT.get(goal, 1.0)

    walk_kcal = sum((w.kcal_burned or 0) for w in WalkingLog.objects.filter(user=user, date=day))

    today_workouts = list(WorkoutLog.objects.filter(user=user, date=day))
    # Тренировка попадает в бюджет ТОЛЬКО после подтверждения (есть workout_log)
    # и по факту — kcal_burned уже посчитан из ВЫПОЛНЕННЫХ упражнений (done_workout_stats).
    # До подтверждения плановый расход НЕ добавляем.
    workout_kcal = sum((w.kcal_burned or 0) for w in today_workouts)

    # Базовый бюджет — БЕЗ активности. На нём действуют пол (безопасный минимум)
    # и потолок. Активность добавляем сверх, иначе на агрессивном дефиците база
    # упирается в пол и расход тренировки/ходьбы становится не виден.
    floor = round(bmr * 1.1)
    cap = round((bmr + baseline) * mult * 1.4)
    base = max(floor, min(cap, round((bmr + baseline) * mult)))
    # «Возврат» части расхода (ходьба + подтверждённая тренировка) в лимит — сверх базы.
    # Потолок по-прежнему ограничивает общее раздувание лимита.
    activity_kcal = round((walk_kcal + workout_kcal) * mult)
    target = min(base + activity_kcal, cap)

    tp = profile.target_protein_g or 0
    tf = profile.target_fat_g or 0
    tc = profile.target_carbs_g or 0

    # Если за сегодня тренировка уже ПОДТВЕРЖДЕНА — показываем её как тренировку дня
    # (а не «отдых»: иначе expected_today видит last=сегодня → days_since=0 < interval).
    if today_workouts:
        w = today_workouts[0]
        bn = parse_workout_number(w.day_plan)
        workout_today = {"is_workout": True, "label": w.day_plan or (f"№{bn}" if bn else "Тренировка"),
                         "block_num": bn, "done": True}
    elif exp["type"] == "workout":
        workout_today = {"is_workout": True, "label": exp["label"], "block_num": exp["number"]}
    else:
        workout_today = {"is_workout": False, "label": None, "block_num": None,
                         "days_until_next": exp.get("days_until_next")}

    # серии (🔥): читаем напрямую из Streak, чтобы не плодить циклический импорт со streak.py
    streaks = {}
    rows = {s.kind: s for s in Streak.objects.filter(user=user)}
    for kind in ("nutrition", "workout"):
        s = rows.get(kind)
        streaks[kind] = {"current": s.current if s else 0,
                         "longest": s.longest if s else 0,
                         "status": s.status if s else "active"}

    # маскот-лис: если серии ещё нет — стартуем от параметров тела (база нового юзера)
    w_row, n_row = rows.get("workout"), rows.get("nutrition")
    muscle_score = w_row.level_score if w_row else initial_score(profile, "workout")
    belly_score = n_row.level_score if n_row else initial_score(profile, "nutrition")
    avatar = {
        "muscle_tier": muscle_tier(muscle_score),
        "belly_tier": belly_tier(belly_score),
    }

    return {
        "ok": True,
        "date": day.isoformat(),
        "workout_today": workout_today,
        "kcal": {"target": target, "eaten": today_sum["kcal"], "left": round(target - today_sum["kcal"])},
        "protein": {"target": tp, "eaten": today_sum["protein"], "left": r1(tp - today_sum["protein"])},
        "fat": {"target": tf, "eaten": today_sum["fat"]},
        "carbs": {"target": tc, "eaten": today_sum["carbs"]},
        "streaks": streaks,
        "avatar": avatar,
    }


def active_blocks_list(user):
    state = blocks_state(user)
    return [{"block_num": n, "label": state[n]["label"]}
            for n in sorted(n for n, v in state.items() if v["active"])]


def block_exercises(user, day, block):
    done = {
        d.exercise.strip()
        for d in WorkoutDone.objects.filter(user=user, date=day, block_num=block, done=True)
    }
    profile = getattr(user, "profile", None)
    uw = (profile.weight_kg if profile else None) or 76
    out = []
    for r in WorkoutCatalog.objects.filter(user=user, block_num=block):
        if not r.exercise:
            continue
        ex = r.exercise.strip()
        weight = r.weight if r.weight not in (None, "", "—") else ""
        auto_kcal = exercise_auto_kcal(r, uw)
        out.append({
            "id": f"{block}::{ex}",
            "db_id": r.id,
            "group": r.group or "",
            "exercise": ex,
            "sets": str(r.sets) if r.sets not in (None, "") else "",
            "reps": str(r.reps) if r.reps not in (None, "") else "",
            "weight": str(weight) if weight else "",
            "note": r.note or "",
            "met": r.met,
            "default_min": r.default_min,
            "kcal_override": r.kcal_override,        # ручной расход (или null)
            "kcal_auto": auto_kcal,                  # авто-оценка для подсказки в форме
            "kcal": r.kcal_override if r.kcal_override is not None else auto_kcal,
            "done": ex in done,
        })
    return out


def compute_workout(user, day, forced_block=None):
    """План на выбранный день + выбор блока. Работает для ЛЮБОГО дня (backdating):
    - forced_block задан (юзер ткнул чип) → его;
    - есть workout_log за день → его блок;
    - сегодня и по циклу тренировка → ожидаемый блок;
    - иначе (прошлый день без лога) → блок не выбран, юзер выбирает сам.
    """
    from django.utils import timezone
    blocks = active_blocks_list(user)
    active_nums = [b["block_num"] for b in blocks]
    is_today = (day == timezone.localdate())

    logged = WorkoutLog.objects.filter(user=user, date=day).first()
    exp = expected_today(user, day) if is_today else None

    if forced_block:
        selected = forced_block
    elif logged:
        selected = parse_workout_number(logged.day_plan)
    elif is_today and exp and exp["type"] == "workout":
        selected = exp["number"]
    else:
        selected = None
    if selected not in active_nums:
        selected = None

    label = next((b["label"] for b in blocks if b["block_num"] == selected), None)
    result = {
        "ok": True,
        "date": day.isoformat(),
        "is_today": is_today,
        "blocks": blocks,
        "selected_block": selected,
        "label": label,
        "logged": bool(logged),
        "exercises": block_exercises(user, day, selected) if selected else [],
        # расчётный расход по уже отмеченным упражнениям (для кнопки «Завершить»)
        "est_kcal": done_workout_stats(user, day, selected)[0] if selected else 0,
    }
    # подсказка про отдых только для сегодня, если по циклу выходной
    if is_today and exp and exp["type"] == "rest":
        result["rest_hint_days"] = exp.get("days_until_next")
    return result
