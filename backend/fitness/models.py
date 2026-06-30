"""
Модели = листы Google Sheets, переведённые в реляционную схему.
Заложен мультиюзер (TgUser + FK), хотя сейчас один пользователь.
Уникальные ключи там, где в Sheets были костыли (upsert по составному ключу).
"""
from django.db import models
from django.utils import timezone


class TgUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=128, blank=True, default="")
    # Приложение открыто всем (approved=True по умолчанию) — это бан-рычаг владельца.
    approved = models.BooleanField(default=True)
    # Доступ к AI-боту выдаёт владелец вручную (по умолчанию выключен).
    has_bot_access = models.BooleanField(default=False)
    # Сколько обращений к AI-боту в сутки разрешено (правится в админке per-user).
    bot_daily_limit = models.IntegerField(default=5)
    # Платная подписка активна до этого момента (null = никогда не оплачивал).
    # Заполняется колбэком об успешной оплате (см. Payment / views.payments_*).
    subscription_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.telegram_id} ({self.first_name})"

    @property
    def subscription_active(self):
        return bool(self.subscription_until and self.subscription_until >= timezone.now())


class Payment(models.Model):
    """Транзакция оплаты подписки (провайдер — Platega). Создаётся при нажатии
    «оформить подписку» (status=PENDING), обновляется колбэком о статусе.
    Заготовка: пока платежи не настроены (нет MERCHANT_ID/SECRET) — не используется."""
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="payments")
    transaction_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    amount = models.IntegerField(default=0)              # в валюте провайдера (RUB)
    currency = models.CharField(max_length=8, default="RUB")
    method = models.IntegerField(default=2)              # Platega paymentMethod (2=СБП, …)
    status = models.CharField(max_length=24, default="PENDING")  # PENDING/CONFIRMED/CANCELED/CHARGEBACKED/ERROR
    plan = models.CharField(max_length=32, blank=True, default="")
    payload = models.CharField(max_length=255, blank=True, default="")  # наш внутренний payload
    pay_url = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "status"], name="fitness_pay_user_status_idx")]

    def __str__(self):
        return f"{self.user_id} {self.amount}{self.currency} {self.status}"


class BotUsage(models.Model):
    """Счётчик обращений к AI-боту по дням (для суточного лимита). Бот (n8n)
    апсёртит count на каждое разрешённое сообщение; сравнение с TgUser.bot_daily_limit."""
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="bot_usage")
    date = models.DateField()
    count = models.IntegerField(default=0)

    class Meta:
        unique_together = [("user", "date")]
        indexes = [models.Index(fields=["user", "date"])]

    def __str__(self):
        return f"{self.user_id} {self.date}: {self.count}"


class Profile(models.Model):
    user = models.OneToOneField(TgUser, on_delete=models.CASCADE, related_name="profile")
    height_cm = models.FloatField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    age = models.IntegerField(null=True, blank=True)
    sex = models.CharField(max_length=8, blank=True, default="")
    activity_level = models.CharField(max_length=32, blank=True, default="")
    goal = models.CharField(max_length=16, blank=True, default="maintain")
    daily_baseline_kcal = models.IntegerField(null=True, blank=True)
    bmr = models.IntegerField(null=True, blank=True)
    training_days_interval = models.IntegerField(null=True, blank=True)
    target_kcal = models.IntegerField(null=True, blank=True)
    target_protein_g = models.FloatField(null=True, blank=True)
    target_fat_g = models.FloatField(null=True, blank=True)
    target_carbs_g = models.FloatField(null=True, blank=True)
    # Преференсы Mini App. notifications_enabled — общий тумблер крон-рассылки
    # (серии всё равно считаются, глушится только отправка). theme — "light" | "dark".
    notifications_enabled = models.BooleanField(default=True)
    theme = models.CharField(max_length=8, blank=True, default="light")
    updated_at = models.DateTimeField(auto_now=True)


class FoodLog(models.Model):
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="food_log")
    date = models.DateField()
    time = models.CharField(max_length=8, blank=True, default="")
    description = models.TextField(blank=True, default="")
    kcal = models.IntegerField(default=0)
    protein = models.FloatField(default=0)
    fat = models.FloatField(default=0)
    carbs = models.FloatField(default=0)
    meal_type = models.CharField(max_length=32, blank=True, default="")
    # вес порции в граммах. null = граммовка неизвестна (порционная запись) —
    # такую правим только числами КБЖУ; если задан — правка пересчётом по граммам.
    grams = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "date"])]


class WorkoutLog(models.Model):
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="workout_log")
    date = models.DateField()
    day_plan = models.CharField(max_length=128, blank=True, default="")
    exercises_done = models.TextField(blank=True, default="")
    duration_min = models.IntegerField(null=True, blank=True)
    kcal_burned = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(max_length=32, blank=True, default="")  # bot|app|apple_watch
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # одна тренировка в день → upsert «завершить тренировку»
        unique_together = [("user", "date")]


class WorkoutDone(models.Model):
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="workout_done")
    date = models.DateField()
    block_num = models.IntegerField()
    exercise = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "date", "block_num", "exercise")]


class WalkingLog(models.Model):
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="walking_log")
    date = models.DateField()
    time = models.CharField(max_length=8, blank=True, default="")
    activity = models.CharField(max_length=64, blank=True, default="")
    duration_min = models.IntegerField(null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    speed_kmh = models.FloatField(null=True, blank=True)
    kcal_burned = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(max_length=32, blank=True, default="")  # bot|app|apple_watch

    class Meta:
        indexes = [models.Index(fields=["user", "date"])]


class WaterLog(models.Model):
    """Дневной счётчик воды (мл). Один апсерт-ряд на день."""
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="water_log")
    date = models.DateField()
    ml = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "date")]


class BodyParams(models.Model):
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="body_params")
    date = models.DateField()
    weight = models.FloatField(null=True, blank=True)
    body_fat_pct = models.FloatField(null=True, blank=True)
    # обхваты (см) — динамика тела для экрана «Прогресс»
    waist = models.FloatField(null=True, blank=True)
    chest = models.FloatField(null=True, blank=True)
    hips = models.FloatField(null=True, blank=True)
    biceps = models.FloatField(null=True, blank=True)
    thigh = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")


class Product(models.Model):
    # глобальный справочник продуктов (по штрихкоду)
    barcode = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    aliases = models.CharField(max_length=200, blank=True, default="")
    kcal_per_100g = models.FloatField(null=True, blank=True)
    protein_per_100g = models.FloatField(null=True, blank=True)
    fat_per_100g = models.FloatField(null=True, blank=True)
    carbs_per_100g = models.FloatField(null=True, blank=True)
    default_serving_g = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")


class WorkoutCatalog(models.Model):
    # план тренировок пользователя (был лист workouts_flat)
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="workouts")
    block_num = models.IntegerField()
    group = models.CharField(max_length=64, blank=True, default="")
    exercise = models.CharField(max_length=200)
    sets = models.CharField(max_length=16, blank=True, default="")
    reps = models.CharField(max_length=16, blank=True, default="")
    weight = models.CharField(max_length=32, blank=True, default="")
    note = models.CharField(max_length=200, blank=True, default="")
    met = models.FloatField(null=True, blank=True)
    default_min = models.IntegerField(null=True, blank=True)
    # ручной расход за упражнение: задан → используем его вместо MET-формулы; null → авто
    kcal_override = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "block_num"])]


class WorkoutBlock(models.Model):
    # вкл/выкл блоков плана + их лейблы (был лист workout_blocks)
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="workout_blocks")
    block_num = models.IntegerField()
    label = models.CharField(max_length=64, blank=True, default="")
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "block_num")]


class Streak(models.Model):
    """Серия (Duolingo-style) — отдельно для питания и тренировок.
    Логика заморозки: 1 промах → frozen (предупреждение), 2-й подряд → сброс."""
    KIND_CHOICES = [("nutrition", "Питание"), ("workout", "Тренировки")]
    STATUS_CHOICES = [("active", "active"), ("frozen", "frozen"), ("reset", "reset")]

    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="streaks")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    current = models.IntegerField(default=0)
    longest = models.IntegerField(default=0)
    # «физический» счётчик маскота 0..100, старт 50 (середина). Двунаправленный:
    # успех дня → +, промах → −. Питание → ось живота, тренировки → ось мышц.
    level_score = models.IntegerField(default=50)
    misses_in_row = models.IntegerField(default=0)       # промахов подряд (для заморозки)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default="active")
    last_ok_date = models.DateField(null=True, blank=True)   # последний засчитанный день
    last_eval_date = models.DateField(null=True, blank=True)  # последний оценённый день (идемпотентность)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "kind")]


class DayResult(models.Model):
    """Кэш дневной оценки (для истории/календаря + идемпотентности).
    workout_ok = NULL → день не был тренировочным по циклу (нейтральный для серии)."""
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="day_results")
    date = models.DateField()
    nutrition_ok = models.BooleanField(null=True, blank=True)
    workout_ok = models.BooleanField(null=True, blank=True)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "date")]
        indexes = [models.Index(fields=["user", "date"], name="dayresult_user_date_idx")]


class ExerciseLibrary(models.Model):
    """Глобальный справочник упражнений (курированный RU-набор). Источник — JSON в публичном
    фронт-репо, синхронизируется кроном раз в месяц. Апсерт по `key`."""
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    section = models.CharField(max_length=32, blank=True, default="")   # Разминка/Силовая/Кор/Кардио/Заминка
    muscle_group = models.CharField(max_length=64, blank=True, default="")
    equipment = models.CharField(max_length=128, blank=True, default="")
    sets = models.CharField(max_length=16, blank=True, default="")
    reps = models.CharField(max_length=32, blank=True, default="")
    met = models.FloatField(null=True, blank=True)
    default_min = models.IntegerField(null=True, blank=True)
    cue = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
