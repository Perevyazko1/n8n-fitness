"""
Серии (Duolingo-style) + напоминания о еде. Единый источник логики, дёргается
cron-эндпоинтами (n8n-крон по расписанию). Считает по ВСЕМ approved-юзерам.

Правила (все пороги — константы ниже, легко крутить):
  • Две раздельные серии: 🍽 nutrition и 🏋 workout.
  • День засчитан:
      nutrition — логировал еду И съел ≥ 50% от плана ккал (мягкий порог: главное — не
                  пропускать лог и не голодать в ноль; белок/перебор серию НЕ рвут);
      workout   — выполнил плановую тренировку (или по циклу был отдых → день нейтральный).
  • Заморозка: 1 промах → frozen (серия на паузе + предупреждение),
               2-й промах подряд → серия сгорает (current=0). Успех всё размораживает.
"""
from datetime import date as date_cls, timedelta

from django.db.models import Max
from django.utils import timezone

from . import calc
from .models import (
    BodyParams, DayResult, FoodLog, Streak, TgUser, WalkingLog, WorkoutLog,
)

# --- порог «день засчитан» по питанию для СЕРИИ (крутить тут) ---
NUTRI_KCAL_MIN_STREAK = 0.50  # для серии: съедено ≥ 50% плана (залогировал и не голодал в ноль)

# --- пороги для ФОРМЫ лисёнка (живот), к серии отношения не имеют ---
NUTRI_KCAL_LOW = 0.80   # ниже — «недоел», тело не трогаем
NUTRI_KCAL_HIGH = 1.10  # выше — «переел», живот растёт

# на каких значениях серии слать поздравление (иначе тихо — видно в приложении)
MILESTONES = {3, 7, 14, 21, 30, 50, 75, 100, 150, 200, 300, 365}

# Форма лисёнка (level_score 0..100, тиры по 25). Двунаправленно, по факту дня:
#   живот: поел в рамках → уходит (+), переел → растёт (−), недоел/не логировал → 0;
#   мышцы (только в трен-дни): трен сделана → растут (+), пропуск → уходят (−).
# ~3–4 дня подряд одного поведения = сдвиг на тир. Крутить тут.
BELLY_IN = 8       # КБЖУ в коридоре → живот уходит
BELLY_OVER = -8    # переел (>110% ккал) → живот растёт
MUSCLE_DONE = 8    # плановая трен выполнена → мышцы растут
MUSCLE_MISS = -10  # плановую трен пропустил → мышцы уходят (запущенность наказуема)

KIND_EMOJI = {"nutrition": "🍽", "workout": "🏋"}
KIND_WORD = {"nutrition": "по питанию", "workout": "по тренировкам"}


# ============================ оценка дня ============================
def nutrition_eval(user, day):
    """(ok_for_streak, belly_delta) за день по питанию.
    ok = логировал И съел ≥ 50% плана ккал (для серии). belly_delta — куда двигать живот лиса
    (форма по-прежнему реагирует на перебор/коридор/недобор, независимо от серии)."""
    if not FoodLog.objects.filter(user=user, date=day).exists():
        return False, 0
    dash = calc.compute_dashboard(user, day)
    if not dash.get("ok"):
        return False, 0
    k = dash["kcal"]
    target = k.get("target") or 0
    eaten = k.get("eaten") or 0
    if eaten <= 0 or target <= 0:
        return False, 0
    # серия: мягкий порог — съедено не меньше половины плана (белок/перебор серию не рвут)
    ok = bool(eaten >= NUTRI_KCAL_MIN_STREAK * target)
    # живот: переел → растёт; не переел (в коридоре или ниже верхней границы) → уходит;
    # сильно недоел (<80%) → тело не трогаем (это «голод» для слоя эмоций).
    if eaten > NUTRI_KCAL_HIGH * target:
        belly = BELLY_OVER
    elif eaten >= NUTRI_KCAL_LOW * target:
        belly = BELLY_IN
    else:
        belly = 0
    return ok, belly


def workout_opportunity(user, day):
    """(opportunity, ok): был ли день тренировочным по циклу и выполнена ли трен.
    Если за день есть workout_log → точно был трен-день и он выполнен (ok=True).
    Иначе смотрим цикл: expected_today без лога корректно показывает план."""
    if WorkoutLog.objects.filter(user=user, date=day).exists():
        return True, True
    exp = calc.expected_today(user, day)
    if exp["type"] == "workout":
        return True, False  # был трен-день, но не выполнил
    return False, False     # по циклу отдых → нейтрально


def _apply_streak(user, kind, day, ok, score_delta):
    """Двигает серию (счётчик/заморозка) по `ok` и форму лисёнка по `score_delta`
    (двунаправленно, по факту дня). Возвращает текст уведомления (или None)."""
    profile = getattr(user, "profile", None)
    s, _ = Streak.objects.get_or_create(
        user=user, kind=kind,
        defaults={"level_score": calc.initial_score(profile, kind)},
    )
    if s.last_eval_date == day:   # уже оценивали этот день — идемпотентность
        return None
    s.last_eval_date = day
    emoji, word = KIND_EMOJI[kind], KIND_WORD[kind]
    msg = None
    if ok:
        s.current += 1
        s.misses_in_row = 0
        s.status = "active"
        s.last_ok_date = day
        if s.current > s.longest:
            s.longest = s.current
        if s.current in MILESTONES:
            msg = f"{emoji}🔥 Серия {word}: {s.current} дн подряд! Так держать."
    else:
        s.misses_in_row += 1
        if s.misses_in_row >= 2:
            lost = s.current
            s.current = 0
            s.status = "reset"
            if lost > 0:
                msg = f"💔 Серия {word} сгорела (была {lost} дн). Ничего — начинаем заново, погнали!"
        else:
            s.status = "frozen"
            if s.current > 0:
                msg = (f"⚠️ Сегодня не закрыл день {word} — серия {emoji}🔥{s.current} "
                       f"заморожена. Ещё один пропуск и сгорит!")
    # форма лисёнка двигается по факту дня, НЕЗАВИСИМО от заморозки серии
    s.level_score = max(0, min(100, s.level_score + score_delta))
    s.save()
    return msg


def evaluate_day(user, day):
    """Оценивает день одного юзера, двигает обе серии, кэширует DayResult.
    Возвращает список текстов для отправки этому юзеру.

    Отключённый домен (nutrition_enabled/workout_enabled = False) НЕ двигает свою серию
    и ось лисёнка, а в DayResult пишется None. DayResult при этом всё равно создаётся —
    курсор catch_up (Max(date)) двигается, поэтому при повторном включении домена
    прошлые «отключённые» дни не засчитаются задним числом как промахи."""
    profile = getattr(user, "profile", None)
    nutri_on = getattr(profile, "nutrition_enabled", True) if profile else True
    workout_on = getattr(profile, "workout_enabled", True) if profile else True

    nutri_ok, belly_delta = nutrition_eval(user, day)
    w_opp, w_ok = workout_opportunity(user, day)
    muscle_delta = (MUSCLE_DONE if w_ok else MUSCLE_MISS) if w_opp else 0

    DayResult.objects.update_or_create(
        user=user, date=day,
        defaults={"nutrition_ok": (nutri_ok if nutri_on else None),
                  "workout_ok": (w_ok if (w_opp and workout_on) else None)},
    )

    msgs = []
    if nutri_on:
        m = _apply_streak(user, "nutrition", day, nutri_ok, belly_delta)
        if m:
            msgs.append(m)
    if w_opp and workout_on:  # форму/серию мышц двигаем только в трен-дни (отдых нейтрален)
        m = _apply_streak(user, "workout", day, w_ok, muscle_delta)
        if m:
            msgs.append(m)
    return msgs


def catch_up(user, upto=None):
    """Догоняет все ЗАВЕРШЁННЫЕ (≤ вчера), ещё не оценённые дни этого юзера.
    Делает серию независимой от крона: при заходе в приложение и при логировании
    пропущенные дни доеоцениваются сами. Сегодня НЕ трогаем — день ещё не закрыт.

    Курсор — max(DayResult.date): это «последний полностью оценённый день». Идём от
    него +1 до вчера. Так не передаём в evaluate_day уже оценённые дни (иначе слабый
    per-kind guard мог бы их пересчитать). Идемпотентно и безопасно при гонке с кроном.
    Возвращает накопленные сообщения (вехи/заморозки) — на случай отправки."""
    yesterday = (upto or timezone.localdate()) - timedelta(days=1)
    last = DayResult.objects.filter(user=user).aggregate(m=Max("date"))["m"]
    # новый юзер без истории — не отматываем прошлое, оцениваем только вчера
    start = (last + timedelta(days=1)) if last else yesterday
    msgs, d, guard = [], start, 0
    while d <= yesterday and guard < 400:
        msgs += evaluate_day(user, d)
        d += timedelta(days=1)
        guard += 1
    return msgs


def evaluate_all(day):
    """Оценить день по всем approved-юзерам. Возвращает [{chat_id, text}] для рассылки.
    ВАЖНО: серии/форма двигаются ВСЕГДА; тумблер `notifications_enabled` глушит только
    рассылку (юзер без уведомлений всё равно копит серию — видит её в приложении)."""
    out = []
    for user in TgUser.objects.filter(approved=True):
        profile = getattr(user, "profile", None)
        if not profile:
            continue
        msgs = evaluate_day(user, day)
        if not profile.notifications_enabled:
            continue
        for text in msgs:
            out.append({"chat_id": user.telegram_id, "text": text})
    return out


# ============================ напоминания о еде ============================
REMINDER_TEXTS = {
    "afternoon": "🍽 Заметил, что ты сегодня ещё ничего не записал. Что ел на завтрак/обед? "
                 "Скинь — посчитаю КБЖУ.",
    "evening": "🌙 За весь день ни одной записи о еде. Если ел — занеси, чтобы КБЖУ и серия "
               "🔥 не пострадали.",
}


def meal_reminders(window, day):
    """[{chat_id, text}] — approved-юзерам с профилем и включёнными уведомлениями,
    у кого за `day` пусто в food_log."""
    text = REMINDER_TEXTS.get(window, REMINDER_TEXTS["afternoon"])
    out = []
    for user in TgUser.objects.filter(approved=True):
        profile = getattr(user, "profile", None)
        if not profile or not profile.notifications_enabled or not profile.nutrition_enabled:
            continue
        if FoodLog.objects.filter(user=user, date=day).exists():
            continue
        out.append({"chat_id": user.telegram_id, "text": text})
    return out


def morning_messages(day):
    """[{chat_id, text}] — утренний план на день, ПО КАЖДОМУ approved-юзеру отдельно.

    Раньше это считал JS-нод в n8n, который читал fitness_profile / fitness_workoutcatalog
    БЕЗ WHERE user_id: план собирался из упражнений всех юзеров разом, а слался одному
    (первому из выборки). Теперь всё считается тут, на тех же функциях, что и Mini App
    (expected_today / block_exercises / GOAL_MULT) — один источник правды.
    """
    out = []
    for user in TgUser.objects.filter(approved=True).select_related("profile"):
        profile = getattr(user, "profile", None)
        if not profile or not profile.notifications_enabled:
            continue
        text = _morning_text(user, profile, day)
        if text:
            out.append({"chat_id": user.telegram_id, "text": text})
    return out


# --- недельная сводка (воскресенье 21:00) ---
WEEKLY_PROTEIN_TOLERANCE = 10   # «белок добран», если не ниже цели больше чем на 10 г


def weekly_reports(day):
    """[{chat_id, text}] — итоги недели (7 дней, включая `day`) по каждому юзеру.

    Раньше считал JS-нод в n8n: четыре запроса (еда/тренировки/ходьба/замеры) БЕЗ
    WHERE user_id, а получатель — `profileRows.find(r => r.chat_id)`, то есть первый
    профиль в выборке. Отчёт получал один человек, а цифры в нём были сложены по всем.
    """
    out = []
    for user in TgUser.objects.filter(approved=True).select_related("profile"):
        profile = getattr(user, "profile", None)
        if not profile or not profile.notifications_enabled:
            continue
        text = _weekly_text(user, profile, day)
        if text:
            out.append({"chat_id": user.telegram_id, "text": text})
    return out


def _weekly_text(user, profile, day):
    """Текст сводки или None, если оба домена отслеживания выключены."""
    nutrition = profile.nutrition_enabled
    workouts = profile.workout_enabled
    if not nutrition and not workouts:
        return None

    start = day - timedelta(days=6)
    lines = [f"📊 Итоги недели ({start.isoformat()} — {day.isoformat()})"]

    if workouts:
        logs = list(WorkoutLog.objects.filter(user=user, date__range=(start, day)).order_by("date"))
        expected = 7 // max(1, profile.training_days_interval or 1)
        burned = sum((w.kcal_burned or 0) for w in logs)
        lines += ["", f"🏋 Тренировок: {len(logs)} из ~{expected} ожидаемых, "
                      f"расход ~{round(burned)} ккал"]
        for w in logs:
            dur = f"{w.duration_min} мин" if w.duration_min else "? мин"
            kcal = f"~{w.kcal_burned} ккал" if w.kcal_burned else "? ккал"
            crowd = ""
            if w.crowd is not None:
                crowd = " · много народу" if w.crowd else " · свободно"
            lines.append(f"- {w.day_plan or '?'} — {dur}, {kcal}{crowd}")

        walks = list(WalkingLog.objects.filter(user=user, date__range=(start, day)))
        walk_days = len({w.date for w in walks})
        walk_min = sum((w.duration_min or 0) for w in walks)
        walk_kcal = sum((w.kcal_burned or 0) for w in walks)
        lines += ["", f"🚶 Ходьба: {walk_days} из 7 дней "
                      f"(всего {walk_min} мин, ~{round(walk_kcal)} ккал)"]
        if walk_days:
            lines.append(f"- В среднем {round(walk_min / walk_days)} мин в день, когда ходил")
        else:
            lines.append("- За неделю ходьба ни разу не залогирована — при сидячей работе это слабо.")

    # вес/жир показываем всегда: это прогресс тела, а не «питание»
    body = list(BodyParams.objects.filter(user=user, date__range=(start, day)).order_by("date"))
    weight_delta = None
    with_weight = [b for b in body if b.weight]
    if len(with_weight) >= 2:
        w0, w1 = with_weight[0].weight, with_weight[-1].weight
        weight_delta = w1 - w0
        lines += ["", f"⚖️ Вес: {w0} → {w1} кг ({weight_delta:+.1f} кг)"]
        f0, f1 = with_weight[0].body_fat_pct, with_weight[-1].body_fat_pct
        if f0 and f1:
            lines.append(f"📉 % жира: {f0} → {f1} ({f1 - f0:+.1f})")
    elif len(with_weight) == 1:
        lines += ["", f"⚖️ Вес: {with_weight[0].weight} кг (одно измерение, динамики нет)"]
    else:
        lines += ["", "⚖️ Вес: данных за неделю нет."]

    if nutrition:
        wk = calc.weekly_deficit(user, day, days=7)
        logged = wk["logged_days"]
        lines += ["", f"🍽 Еда: {logged} из 7 дней залогированы"]
        if logged:
            eaten_sum = sum(d["eaten"] for d in wk["per_day"] if d["logged"])
            target_sum = sum(d["target"] for d in wk["per_day"] if d["logged"])
            protein_target = round(profile.target_protein_g or 0)
            protein_days, protein_sum = 0, 0.0
            for d in wk["per_day"]:
                if not d["logged"]:
                    continue
                got = calc._food_sum(user, date_cls.fromisoformat(d["date"]))["protein"]
                protein_sum += got
                if protein_target and got >= protein_target - WEEKLY_PROTEIN_TOLERANCE:
                    protein_days += 1
            lines.append(f"- Средние ккал: {round(eaten_sum / logged)} "
                         f"(цель ~{round(target_sum / logged)})")
            lines.append(f"- Средний белок: {round(protein_sum / logged)}г "
                         f"(цель {protein_target}г)")
            lines.append(f"- Белок добран в {protein_days} из {logged} дней "
                         f"({round(100 * protein_days / logged)}%)")
            sign = "дефицит" if wk["total"] >= 0 else "профицит"
            lines.append(f"- Накопленный {sign}: {abs(wk['total'])} ккал "
                         f"({abs(wk['avg'])} ккал/день)")

    lines += ["", f"💡 {_weekly_verdict(weight_delta, profile)}"]
    return "\n".join(lines)


def _weekly_verdict(weight_delta, profile):
    """Вердикт по темпу. Знак «хорошего» изменения веса зависит от ЦЕЛИ: на похудении
    хотим минус, на массе — плюс. Старый n8n этого не учитывал и ругал набор веса
    даже тем, кто набирает осознанно."""
    if weight_delta is None:
        return "Чтобы видеть динамику, взвешивайся хотя бы 1-2 раза в неделю."
    goal = (profile.goal or "maintain").lower()
    if goal == "gain":
        if weight_delta > 0.7:
            return "⚠️ Набор быстрее, чем нужно — часть уйдёт в жир. Сбавь профицит."
        if weight_delta >= 0.2:
            return "✅ Хороший темп набора. Продолжай."
        return "😐 Масса не растёт — добавь калорий и следи за белком."
    if goal == "lose":
        if weight_delta < -1.2:
            return "⚠️ Дефицит может быть слишком велик — подними ккал, чтобы не терять мышцы."
        if weight_delta < -0.3:
            return "✅ Отличный темп! Продолжай в том же духе."
        if weight_delta <= 0.3:
            return "😐 Темп тормозит — проверь точность подсчёта или добавь активности."
        return "⚠️ Вес растёт — пересмотри размеры порций и проверь дефицит."
    if abs(weight_delta) <= 0.5:
        return "✅ Вес держится — ровно то, что нужно на поддержании."
    return ("😐 Вес поехал вниз — если не планировал, добавь калорий."
            if weight_delta < 0 else
            "😐 Вес поехал вверх — проверь порции.")


def workout_pings(day):
    """[{chat_id, text}] — вечерний пинг (23:00) тем, у кого сегодня по циклу была
    тренировка, но подтверждения нет.

    Раньше считал JS-нод в n8n, который читал fitness_workoutlog БЕЗ WHERE user_id:
    «последняя тренировка» и «залогировано сегодня» брались по всем юзерам разом —
    достаточно было ОДНОМУ подтвердить трен, и пинг не получал никто. Плюс названия
    блоков были захардкожены (№1..№4) и цикл считался по модулю 4, игнорируя
    fitness_workoutblock. Теперь всё через expected_today, как в Mini App.
    """
    out = []
    for user in TgUser.objects.filter(approved=True).select_related("profile"):
        profile = getattr(user, "profile", None)
        if not profile or not profile.notifications_enabled or not profile.workout_enabled:
            continue
        opportunity, done = workout_opportunity(user, day)
        if not opportunity or done:
            continue
        exp = calc.expected_today(user, day)
        label = exp.get("label") or "тренировка"
        out.append({"chat_id": user.telegram_id, "text": (
            f"🏋 Эй! Сегодня по плану была тренировка {label}, а отчёта от тебя нет. "
            "Что случилось?\n\n"
            "Если всё-таки тренировался — отметь упражнения в приложении и нажми "
            "«Завершить»: день ещё успеет уйти в серию 🔥"
        )})
    return out


def _morning_text(user, profile, day):
    """Текст утреннего сообщения или None, если юзеру нечего сказать.

    Уважает оба тумблера отслеживания из профиля: при выключенном питании блок
    про калории/белок не показываем вовсе (у юзера нет дневного лимита), при
    выключенных тренировках — не показываем план. Выключено и то и другое → None.
    """
    nutrition = profile.nutrition_enabled
    exp = calc.expected_today(user, day) if profile.workout_enabled else {"type": "off"}
    if not nutrition and exp["type"] == "off":
        return None

    bmr = profile.bmr or 1600
    baseline = profile.daily_baseline_kcal or 280
    mult = calc.GOAL_MULT.get((profile.goal or "maintain").lower(), 1.0)
    protein = round(profile.target_protein_g or 0)

    if exp["type"] == "workout":
        exercises = calc.block_exercises(user, day, exp["number"])
        plan_kcal = round(sum((e.get("kcal") or 0) for e in exercises))
        parts = [f"🌅 Доброе утро! Сегодня {exp['label']}."]
        if nutrition:
            expense = bmr + baseline + plan_kcal
            parts += [
                "",
                "🎯 Ожидаемый расход:",
                f"- BMR: {bmr} ккал",
                f"- Повседневная: {baseline} ккал",
                f"- Тренировка: ~{plan_kcal} ккал",
                f"- Итого: ~{expense} ккал → цель ~{round(expense * mult)} ккал.",
                "",
                "💡 Каждые 30 мин ходьбы (3.5 км/ч) добавят ~107 ккал к бюджету.",
            ]
        lines = []
        for e in exercises:
            sets_reps = "×".join(x for x in (e["sets"], e["reps"]) if x)
            tail = ", ".join(x for x in (sets_reps, e["weight"]) if x)
            group = f"{e['group']}: " if e["group"] else ""
            lines.append(f"- {group}{e['exercise']}" + (f", {tail}" if tail else ""))
        if lines:
            parts += ["", "💪 План:"] + lines
        if nutrition:
            parts += ["", f"🎯 Белок: {protein}г."]
        parts += ["", "Удачи! Жду отчёт вечером."]
        return "\n".join(parts)

    parts = ["🌅 Доброе утро! Сегодня день отдыха." if exp["type"] == "rest"
             else "🌅 Доброе утро!"]
    if nutrition:
        expense = bmr + baseline
        parts += [
            "",
            "🎯 Ожидаемый расход без активности:",
            f"- BMR: {bmr} ккал",
            f"- Повседневная: {baseline} ккал",
            f"- Итого: ~{expense} ккал → цель ~{round(expense * mult)} ккал.",
            "",
            "💡 Чтобы добавить бюджет — походи. 30 мин = +107 ккал, 90 мин = +320 ккал.",
            "",
            f"🎯 Белок: {protein}г.",
        ]
    if exp["type"] == "rest":
        nxt = calc.expected_today(user, day + timedelta(days=exp.get("days_until_next") or 1))
        if nxt["type"] == "workout":
            parts += ["", f"💤 Следующая тренировка — {nxt['label']}."]
    return "\n".join(parts)


def undereating_warnings(day):
    """[{chat_id, text}] — на 22:00: кто за день съел < 50% плана ккал (в т.ч. 0).
    Рыж предупреждает, что день не пойдёт в серию и что недоедание — плохо.
    Уважает тумблер уведомлений."""
    out = []
    for user in TgUser.objects.filter(approved=True):
        profile = getattr(user, "profile", None)
        if not profile or not profile.notifications_enabled or not profile.nutrition_enabled:
            continue
        dash = calc.compute_dashboard(user, day)
        if not dash.get("ok"):
            continue
        target = dash["kcal"].get("target") or 0
        eaten = dash["kcal"].get("eaten") or 0
        if target <= 0 or eaten >= NUTRI_KCAL_MIN_STREAK * target:
            continue
        text = (
            f"🦊 Рыж не верит, что ты сегодня съел так мало — всего {eaten} из {target} ккал. "
            "Если просто забыл занести — самое время, день ещё можно спасти 🔥. "
            "А если правда так мало — так нельзя: недоедание тормозит и форму, и силы, "
            "и Рыж от этого грустит. Покорми его 🍽"
        )
        out.append({"chat_id": user.telegram_id, "text": text})
    return out


# ============================ для дашборда ============================
def streaks_for_user(user):
    """Текущее состояние серий для Mini App."""
    res = {}
    rows = {s.kind: s for s in Streak.objects.filter(user=user)}
    for kind in ("nutrition", "workout"):
        s = rows.get(kind)
        res[kind] = {
            "current": s.current if s else 0,
            "longest": s.longest if s else 0,
            "status": s.status if s else "active",
        }
    return res
