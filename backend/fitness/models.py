"""
Модели = листы Google Sheets, переведённые в реляционную схему.
Заложен мультиюзер (TgUser + FK), хотя сейчас один пользователь.
Уникальные ключи там, где в Sheets были костыли (upsert по составному ключу).
"""
from django.db import models


class TgUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.telegram_id} ({self.first_name})"


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

    class Meta:
        indexes = [models.Index(fields=["user", "date"])]


class BodyParams(models.Model):
    user = models.ForeignKey(TgUser, on_delete=models.CASCADE, related_name="body_params")
    date = models.DateField()
    weight = models.FloatField(null=True, blank=True)
    body_fat_pct = models.FloatField(null=True, blank=True)
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
