"""
Регистрация моделей в Django-админке (/admin/) — для просмотра и ручной правки
данных владельцем. На /api/ (Mini App) это не влияет: админка живёт на своих
сессиях/паролях, API — на Telegram initData.
"""
from django.contrib import admin

from .models import (
    BodyParams, BotUsage, DayResult, ExerciseLibrary, FoodLog, Payment, Product, Profile,
    Streak, TgUser, WalkingLog, WaterLog, WorkoutBlock, WorkoutCatalog, WorkoutDone, WorkoutLog,
)


@admin.register(TgUser)
class TgUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "first_name", "approved", "has_bot_access", "subscription_until", "bot_daily_limit", "created_at")
    list_filter = ("approved", "has_bot_access")
    # лимит и доступы правятся прямо из списка
    list_editable = ("approved", "has_bot_access", "bot_daily_limit")
    search_fields = ("telegram_id", "first_name")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "currency", "status", "plan", "transaction_id", "created_at")
    list_filter = ("status", "currency")
    search_fields = ("user__telegram_id", "transaction_id")
    date_hierarchy = "created_at"


@admin.register(BotUsage)
class BotUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "count")
    list_filter = ("date",)
    search_fields = ("user__telegram_id", "user__first_name")
    date_hierarchy = "date"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "sex", "goal", "weight_kg", "height_cm", "target_kcal",
                    "theme", "notifications_enabled", "updated_at")
    search_fields = ("user__telegram_id", "user__first_name")


@admin.register(FoodLog)
class FoodLogAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "time", "description", "kcal", "protein", "fat", "carbs", "meal_type")
    list_filter = ("date", "meal_type")
    search_fields = ("description", "user__telegram_id")
    date_hierarchy = "date"


@admin.register(WorkoutLog)
class WorkoutLogAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "day_plan", "duration_min", "kcal_burned", "source")
    list_filter = ("date", "source")
    date_hierarchy = "date"


@admin.register(WorkoutDone)
class WorkoutDoneAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "block_num", "exercise", "done", "updated_at")
    list_filter = ("date", "done", "block_num")
    search_fields = ("exercise",)
    date_hierarchy = "date"


@admin.register(WalkingLog)
class WalkingLogAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "activity", "distance_km", "kcal_burned", "source")
    list_filter = ("date", "source")
    date_hierarchy = "date"


@admin.register(BodyParams)
class BodyParamsAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "weight", "body_fat_pct")
    list_filter = ("date",)
    date_hierarchy = "date"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "barcode", "kcal_per_100g", "protein_per_100g",
                    "fat_per_100g", "carbs_per_100g", "default_serving_g")
    search_fields = ("name", "barcode", "aliases")


@admin.register(WorkoutCatalog)
class WorkoutCatalogAdmin(admin.ModelAdmin):
    list_display = ("user", "block_num", "group", "exercise", "sets", "reps", "weight", "kcal_override")
    list_filter = ("block_num", "group")
    search_fields = ("exercise",)


@admin.register(WorkoutBlock)
class WorkoutBlockAdmin(admin.ModelAdmin):
    list_display = ("user", "block_num", "label", "active")
    list_filter = ("active",)


@admin.register(Streak)
class StreakAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "current", "longest", "level_score", "status",
                    "misses_in_row", "last_ok_date", "last_eval_date")
    list_filter = ("kind", "status")


@admin.register(DayResult)
class DayResultAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "nutrition_ok", "workout_ok", "evaluated_at")
    list_filter = ("date", "nutrition_ok", "workout_ok")
    date_hierarchy = "date"


@admin.register(WaterLog)
class WaterLogAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "ml", "updated_at")
    list_filter = ("date",)
    date_hierarchy = "date"


@admin.register(ExerciseLibrary)
class ExerciseLibraryAdmin(admin.ModelAdmin):
    list_display = ("name", "section", "muscle_group", "equipment", "sets", "reps", "met", "updated_at")
    list_filter = ("section", "muscle_group")
    search_fields = ("name", "key", "muscle_group")
