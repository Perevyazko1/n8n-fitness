"""
Серии (Duolingo-style) + напоминания о еде. Единый источник логики, дёргается
cron-эндпоинтами (n8n-крон по расписанию). Считает по ВСЕМ approved-юзерам.

Правила (все пороги — константы ниже, легко крутить):
  • Две раздельные серии: 🍽 nutrition и 🏋 workout.
  • День засчитан:
      nutrition — логировал еду И уложился в КБЖУ (ккал в коридоре, белок ≥ порога);
      workout   — выполнил плановую тренировку (или по циклу был отдых → день нейтральный).
  • Заморозка: 1 промах → frozen (серия на паузе + предупреждение),
               2-й промах подряд → серия сгорает (current=0). Успех всё размораживает.
"""
from . import calc
from .models import DayResult, FoodLog, Streak, TgUser, WorkoutLog

# --- пороги «день засчитан» по питанию (крутить тут) ---
NUTRI_KCAL_LOW = 0.80   # не меньше 80% цели (не голодал)
NUTRI_KCAL_HIGH = 1.10  # не больше 110% цели (не переел)
NUTRI_PROTEIN_MIN = 0.80  # белок ≥ 80% цели

# на каких значениях серии слать поздравление (иначе тихо — видно в приложении)
MILESTONES = {3, 7, 14, 21, 30, 50, 75, 100, 150, 200, 300, 365}

# Храповик «физухи» лисёнка (level_score 0..100). Мотивация: пока НЕ теряешь прогресс
# (серия жива) — лисёнок крепнет; серия сгорела — откат. Старт = от параметров тела.
SCORE_UP = 3     # засчитанный день → крепнет
SCORE_HOLD = 1   # промах, но серия жива (не потерял прогресс) → чуть-чуть растёт
SCORE_RESET = 12  # серия сгорела → заметный откат

KIND_EMOJI = {"nutrition": "🍽", "workout": "🏋"}
KIND_WORD = {"nutrition": "по питанию", "workout": "по тренировкам"}


# ============================ оценка дня ============================
def qualifies_nutrition(user, day):
    """Засчитан ли день по питанию: логировал и уложился в КБЖУ."""
    if not FoodLog.objects.filter(user=user, date=day).exists():
        return False
    dash = calc.compute_dashboard(user, day)
    if not dash.get("ok"):
        return False
    k, p = dash["kcal"], dash["protein"]
    if (k.get("eaten") or 0) <= 0 or (k.get("target") or 0) <= 0:
        return False
    kcal_ok = NUTRI_KCAL_LOW * k["target"] <= k["eaten"] <= NUTRI_KCAL_HIGH * k["target"]
    prot_ok = (p.get("eaten") or 0) >= NUTRI_PROTEIN_MIN * (p.get("target") or 0)
    return bool(kcal_ok and prot_ok)


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


def _apply_streak(user, kind, day, ok):
    """Двигает серию + «физуху» лисёнка на одну оценочную возможность.
    Старт level_score новой серии берём от параметров тела. Возвращает текст (или None)."""
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
        s.level_score = min(100, s.level_score + SCORE_UP)  # крепнет
        if s.current in MILESTONES:
            msg = f"{emoji}🔥 Серия {word}: {s.current} дн подряд! Так держать."
    else:
        s.misses_in_row += 1
        if s.misses_in_row >= 2:
            lost = s.current
            s.current = 0
            s.status = "reset"
            s.level_score = max(0, s.level_score - SCORE_RESET)  # потерял прогресс → откат
            if lost > 0:
                msg = f"💔 Серия {word} сгорела (была {lost} дн). Ничего — начинаем заново, погнали!"
        else:
            s.status = "frozen"
            s.level_score = min(100, s.level_score + SCORE_HOLD)  # серия жива → чуть растём
            if s.current > 0:
                msg = (f"⚠️ Сегодня не закрыл день {word} — серия {emoji}🔥{s.current} "
                       f"заморожена. Ещё один пропуск и сгорит!")
    s.save()
    return msg


def evaluate_day(user, day):
    """Оценивает день одного юзера, двигает обе серии, кэширует DayResult.
    Возвращает список текстов для отправки этому юзеру."""
    nutri_ok = qualifies_nutrition(user, day)
    w_opp, w_ok = workout_opportunity(user, day)

    DayResult.objects.update_or_create(
        user=user, date=day,
        defaults={"nutrition_ok": nutri_ok, "workout_ok": (w_ok if w_opp else None)},
    )

    msgs = []
    m = _apply_streak(user, "nutrition", day, nutri_ok)
    if m:
        msgs.append(m)
    if w_opp:  # серию тренировок двигаем только в трен-дни (отдых нейтрален)
        m = _apply_streak(user, "workout", day, w_ok)
        if m:
            msgs.append(m)
    return msgs


def evaluate_all(day):
    """Оценить день по всем approved-юзерам. Возвращает [{chat_id, text}] для рассылки."""
    out = []
    for user in TgUser.objects.filter(approved=True):
        if not getattr(user, "profile", None):
            continue
        for text in evaluate_day(user, day):
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
    """[{chat_id, text}] — approved-юзерам с профилем, у кого за `day` пусто в food_log."""
    text = REMINDER_TEXTS.get(window, REMINDER_TEXTS["afternoon"])
    out = []
    for user in TgUser.objects.filter(approved=True):
        if not getattr(user, "profile", None):
            continue
        if FoodLog.objects.filter(user=user, date=day).exists():
            continue
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
