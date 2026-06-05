"""
Расчётный сервис — порт логики из n8n (`Build Context` / `Compute Dashboard` /
`Compute Workout Today`). ЕДИНОЕ место вместо трёх дублей.
Никакого LLM — чистая детерминированная математика.
"""
import re

from .models import (
    FoodLog, WalkingLog, WorkoutBlock, WorkoutCatalog, WorkoutDone, WorkoutLog,
)

GOAL_MULT = {"lose": 0.8, "maintain": 1.0, "gain": 1.15}


def r1(x):
    return round((float(x) if x is not None else 0.0) * 10) / 10


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
        for n in (1, 2, 3, 4):
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
    workout_kcal_actual = sum((w.kcal_burned or 0) for w in today_workouts)
    workout_kcal_planned = planned_workout_kcal(user, exp["number"]) if exp["type"] == "workout" else 0
    workout_kcal = workout_kcal_actual if today_workouts else round(workout_kcal_planned)

    tdee = bmr + baseline + walk_kcal + workout_kcal
    target_raw = round(tdee * mult)
    floor = round(bmr * 1.1)
    cap = round((bmr + baseline) * mult * 1.4)
    target = max(floor, min(cap, target_raw))

    tp = profile.target_protein_g or 0
    tf = profile.target_fat_g or 0
    tc = profile.target_carbs_g or 0

    if exp["type"] == "workout":
        workout_today = {"is_workout": True, "label": exp["label"], "block_num": exp["number"]}
    else:
        workout_today = {"is_workout": False, "label": None, "block_num": None,
                         "days_until_next": exp.get("days_until_next")}

    return {
        "ok": True,
        "date": day.isoformat(),
        "workout_today": workout_today,
        "kcal": {"target": target, "eaten": today_sum["kcal"], "left": round(target - today_sum["kcal"])},
        "protein": {"target": tp, "eaten": today_sum["protein"], "left": r1(tp - today_sum["protein"])},
        "fat": {"target": tf, "eaten": today_sum["fat"]},
        "carbs": {"target": tc, "eaten": today_sum["carbs"]},
    }


def compute_workout_today(user, day):
    exp = expected_today(user, day)
    if exp["type"] != "workout":
        return {"ok": True, "date": day.isoformat(), "is_workout": False, "label": None,
                "block_num": None, "days_until_next": exp.get("days_until_next"), "exercises": []}

    block = exp["number"]
    done = {
        d.exercise.strip()
        for d in WorkoutDone.objects.filter(user=user, date=day, block_num=block, done=True)
    }
    exercises = []
    for r in WorkoutCatalog.objects.filter(user=user, block_num=block):
        if not r.exercise:
            continue
        ex = r.exercise.strip()
        weight = r.weight if r.weight not in (None, "", "—") else ""
        exercises.append({
            "id": f"{block}::{ex}",
            "group": r.group or "",
            "exercise": ex,
            "sets": str(r.sets) if r.sets not in (None, "") else "",
            "reps": str(r.reps) if r.reps not in (None, "") else "",
            "weight": str(weight) if weight else "",
            "note": r.note or "",
            "done": ex in done,
        })
    return {"ok": True, "date": day.isoformat(), "is_workout": True,
            "label": exp["label"], "block_num": block, "exercises": exercises}
