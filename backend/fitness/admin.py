"""
Регистрация моделей в Django-админке (/admin/) — для просмотра и ручной правки
данных владельцем. На /api/ (Mini App) это не влияет: админка живёт на своих
сессиях/паролях, API — на Telegram initData.

Тема — django-unfold (см. UNFOLD в config/settings.py): сайдбар с 4 группами,
фильтры-диапазоны по датам вместо бесконечных списков, действия-кнопки.
Все классы обязаны наследовать unfold.admin.ModelAdmin — иначе формы останутся
сток-джанговскими и тема применится только к обвязке.
"""
from datetime import timedelta

from django.contrib import admin, messages
from django.shortcuts import redirect
from django.utils import timezone
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter, RangeDateFilter, RangeDateTimeFilter,
)
from unfold.decorators import action, display

from .models import (
    BodyParams, BotUsage, DayResult, ExerciseLibrary, FoodLog, Payment, Product, Profile,
    Streak, TgUser, WalkingLog, WaterLog, WorkoutBlock, WorkoutCatalog, WorkoutDone, WorkoutLog,
)

admin.site.site_header = "Рыж"
admin.site.site_title = "Рыж — админка"
admin.site.index_title = "Данные бота"


class UserScopedAdmin(ModelAdmin):
    """База для всех моделей с FK на TgUser.

    - list_select_related — иначе колонка «user» даёт N+1 запрос на строку;
    - autocomplete_fields — вместо селекта со всеми юзерами;
    - list_filter_submit — у фильтров-диапазонов нужна кнопка «Применить».
    """
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    list_filter_submit = True

    @display(description="Пользователь", ordering="user__first_name")
    def user_label(self, obj):
        return f"{obj.user.first_name or '—'} ({obj.user.telegram_id})"


# ---------- Люди и доступ ----------
class ProfileInline(StackedInline):
    model = Profile
    can_delete = False
    max_num = 1
    tab = True
    verbose_name_plural = "Профиль"


class StreakInline(TabularInline):
    model = Streak
    extra = 0
    tab = True
    verbose_name_plural = "Серии"
    fields = ("kind", "current", "longest", "level_score", "status", "last_ok_date")


@admin.register(TgUser)
class TgUserAdmin(ModelAdmin):
    list_display = ("telegram_id", "first_name", "access_badge", "approved",
                    "has_bot_access", "bot_daily_limit", "subscription_until", "created_at")
    list_filter = ("approved", "has_bot_access", ("created_at", RangeDateTimeFilter))
    list_filter_submit = True
    # лимит и доступы правятся прямо из списка
    list_editable = ("approved", "has_bot_access", "bot_daily_limit")
    # «=» → поиск по точному значению: telegram_id это BigInteger, icontains по нему
    # Postgres не умеет (и ломал бы автокомплит на других моделях).
    search_fields = ("=telegram_id", "first_name")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    inlines = (ProfileInline, StreakInline)
    actions = ("grant_bot_access", "revoke_bot_access", "extend_subscription_30d")
    actions_row = ("row_toggle_access",)
    fieldsets = (
        ("Кто это", {"fields": ("telegram_id", "first_name", "created_at")}),
        ("Доступ и подписка", {
            "fields": ("approved", "has_bot_access", "bot_daily_limit", "subscription_until"),
            "description": "approved — пускать в Mini App; has_bot_access — отвечает ли бот в Telegram.",
        }),
    )

    @display(description="Статус", label={
        "подписка": "success", "доступ выдан": "info",
        "только Mini App": "warning", "не пущен": "danger",
    })
    def access_badge(self, obj):
        if obj.subscription_active:
            return "подписка"
        if not obj.approved:
            return "не пущен"
        return "доступ выдан" if obj.has_bot_access else "только Mini App"

    @admin.action(description="Выдать доступ к боту")
    def grant_bot_access(self, request, queryset):
        n = queryset.update(approved=True, has_bot_access=True)
        self.message_user(request, f"Доступ выдан: {n}", messages.SUCCESS)

    @admin.action(description="Отозвать доступ к боту")
    def revoke_bot_access(self, request, queryset):
        n = queryset.update(has_bot_access=False)
        self.message_user(request, f"Доступ отозван: {n}", messages.WARNING)

    @admin.action(description="Продлить подписку на 30 дней")
    def extend_subscription_30d(self, request, queryset):
        now = timezone.now()
        count = 0
        for u in queryset:
            base = u.subscription_until if (u.subscription_until and u.subscription_until > now) else now
            u.subscription_until = base + timedelta(days=30)
            u.has_bot_access = True
            u.save(update_fields=["subscription_until", "has_bot_access"])
            count += 1
        self.message_user(request, f"Подписка продлена: {count}", messages.SUCCESS)

    @action(description="Доступ вкл/выкл", icon="toggle_on")
    def row_toggle_access(self, request, object_id):
        """Кнопка прямо в строке списка — самый частый ручной жест."""
        u = TgUser.objects.get(pk=object_id)
        u.has_bot_access = not u.has_bot_access
        if u.has_bot_access:
            u.approved = True
        u.save(update_fields=["has_bot_access", "approved"])
        return redirect(request.META.get("HTTP_REFERER", "admin:fitness_tguser_changelist"))


@admin.register(Profile)
class ProfileAdmin(UserScopedAdmin):
    list_display = ("user_label", "sex", "goal", "weight_kg", "height_cm", "target_kcal",
                    "theme", "notifications_enabled", "updated_at")
    list_filter = ("goal", "sex", "nutrition_enabled", "workout_enabled")
    search_fields = ("=user__telegram_id", "user__first_name")
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("Физиология", {"fields": ("user", "sex", "age", "height_cm", "weight_kg", "activity_level")}),
        ("Цели и нормы", {"fields": ("goal", "calorie_formula", "bmr", "daily_baseline_kcal",
                                     "target_kcal", "target_protein_g", "target_fat_g", "target_carbs_g",
                                     "training_days_interval", "include_activity_kcal")}),
        ("Настройки приложения", {"fields": ("theme", "notifications_enabled",
                                             "nutrition_enabled", "workout_enabled", "updated_at")}),
    )


@admin.register(Payment)
class PaymentAdmin(UserScopedAdmin):
    list_display = ("user_label", "amount", "currency", "status_badge", "plan", "transaction_id", "created_at")
    list_filter = ("status", "currency", ("created_at", RangeDateTimeFilter))
    search_fields = ("=user__telegram_id", "transaction_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at", "pay_url", "payload")

    @display(description="Статус", label={
        "CONFIRMED": "success", "PENDING": "warning", "CANCELED": "danger", "EXPIRED": "danger",
    })
    def status_badge(self, obj):
        return obj.status


@admin.register(BotUsage)
class BotUsageAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "count")
    list_filter = (("date", RangeDateFilter),)
    search_fields = ("=user__telegram_id", "user__first_name")
    date_hierarchy = "date"
    ordering = ("-date",)


# ---------- Питание ----------
@admin.register(FoodLog)
class FoodLogAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "time", "description", "kcal", "protein", "fat", "carbs", "meal_type")
    list_filter = (("date", RangeDateFilter), "meal_type")
    search_fields = ("description", "=user__telegram_id")
    date_hierarchy = "date"
    ordering = ("-date", "-time")
    readonly_fields = ("created_at",)


@admin.register(WaterLog)
class WaterLogAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "ml", "updated_at")
    list_filter = (("date", RangeDateFilter),)
    search_fields = ("=user__telegram_id", "user__first_name")
    date_hierarchy = "date"
    ordering = ("-date",)
    readonly_fields = ("updated_at",)


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ("name", "barcode", "kcal_per_100g", "protein_per_100g",
                    "fat_per_100g", "carbs_per_100g", "default_serving_g")
    search_fields = ("name", "barcode", "aliases")
    ordering = ("name",)
    list_filter_submit = True


# ---------- Тренировки ----------
@admin.register(WorkoutLog)
class WorkoutLogAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "day_plan", "logged_time", "crowd_badge",
                    "duration_min", "kcal_burned", "source_badge")
    list_filter = (("date", RangeDateFilter), "source", "crowd")
    search_fields = ("=user__telegram_id", "day_plan")
    date_hierarchy = "date"
    ordering = ("-date",)
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Тренировка", {"fields": ("user", "date", "day_plan", "duration_min", "kcal_burned", "source")}),
        ("Зал", {"fields": ("logged_time", "crowd"),
                 "description": "Тумблер «много людей» из Mini App + локальное время окончания. "
                                "Питает экран статистики загруженности (/api/gym-crowd)."}),
        ("Прочее", {"fields": ("exercises_done", "notes", "created_at")}),
    )

    @display(description="Зал", label={"много народу": "danger", "свободно": "success"})
    def crowd_badge(self, obj):
        if obj.crowd is None:
            return "—"
        return "много народу" if obj.crowd else "свободно"

    @display(description="Источник", label={"приложение": "success", "бот": "info", "часы": "warning"})
    def source_badge(self, obj):
        return {"app": "приложение", "bot": "бот", "apple_watch": "часы"}.get(obj.source, obj.source or "—")


@admin.register(WorkoutDone)
class WorkoutDoneAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "block_num", "exercise", "done", "updated_at")
    list_filter = (("date", RangeDateFilter), "done", "block_num")
    search_fields = ("exercise", "=user__telegram_id")
    date_hierarchy = "date"
    ordering = ("-date", "block_num")
    readonly_fields = ("updated_at",)


@admin.register(WorkoutBlock)
class WorkoutBlockAdmin(UserScopedAdmin):
    list_display = ("user_label", "block_num", "label", "active")
    list_filter = ("active",)
    search_fields = ("label", "=user__telegram_id")
    ordering = ("user", "block_num")
    list_editable = ("active",)


@admin.register(WorkoutCatalog)
class WorkoutCatalogAdmin(UserScopedAdmin):
    list_display = ("user_label", "block_num", "group", "exercise", "sets", "reps", "weight", "kcal_override")
    list_filter = ("block_num", "group")
    search_fields = ("exercise", "=user__telegram_id")
    ordering = ("user", "block_num", "group")


@admin.register(ExerciseLibrary)
class ExerciseLibraryAdmin(ModelAdmin):
    list_display = ("name", "section", "muscle_group", "equipment", "sets", "reps", "met", "updated_at")
    list_filter = ("section", "muscle_group")
    search_fields = ("name", "key", "muscle_group")
    ordering = ("section", "name")
    readonly_fields = ("updated_at",)
    list_filter_submit = True


@admin.register(WalkingLog)
class WalkingLogAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "activity", "duration_min", "distance_km", "kcal_burned", "source")
    list_filter = (("date", RangeDateFilter), "source", "activity")
    search_fields = ("activity", "=user__telegram_id")
    date_hierarchy = "date"
    ordering = ("-date",)


# ---------- Прогресс и серии ----------
@admin.register(BodyParams)
class BodyParamsAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "weight", "body_fat_pct", "waist", "chest", "hips")
    list_filter = (("date", RangeDateFilter),)
    search_fields = ("=user__telegram_id", "user__first_name")
    date_hierarchy = "date"
    ordering = ("-date",)
    fieldsets = (
        ("Когда", {"fields": ("user", "date")}),
        ("Основное", {"fields": ("weight", "body_fat_pct")}),
        ("Обхваты", {"fields": ("waist", "chest", "hips", "biceps", "thigh"), "classes": ("collapse",)}),
        ("Заметки", {"fields": ("notes",)}),
    )


@admin.register(Streak)
class StreakAdmin(UserScopedAdmin):
    list_display = ("user_label", "kind", "current", "longest", "level_score", "status_badge",
                    "misses_in_row", "last_ok_date", "last_eval_date")
    list_filter = (("kind", ChoicesDropdownFilter), ("status", ChoicesDropdownFilter))
    search_fields = ("=user__telegram_id", "user__first_name")
    ordering = ("user", "kind")
    readonly_fields = ("updated_at",)

    @display(description="Статус", label={"active": "success", "frozen": "info", "reset": "danger"})
    def status_badge(self, obj):
        return obj.status


@admin.register(DayResult)
class DayResultAdmin(UserScopedAdmin):
    list_display = ("user_label", "date", "nutrition_ok", "workout_ok", "evaluated_at")
    list_filter = (("date", RangeDateFilter), "nutrition_ok", "workout_ok")
    search_fields = ("=user__telegram_id", "user__first_name")
    date_hierarchy = "date"
    ordering = ("-date",)
    readonly_fields = ("evaluated_at",)
