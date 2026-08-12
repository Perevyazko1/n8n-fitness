from django.urls import path

from . import views

# Пути совпадают с прежними n8n-вебхуками (минус префикс /webhook → /api).
urlpatterns = [
    path("health", views.health),
    path("dashboard", views.dashboard),
    path("food-log", views.food_log),
    path("delete-food", views.delete_food),
    path("update-food", views.update_food),
    path("repeat-food", views.repeat_food),
    path("workout-today", views.workout_today),
    path("toggle-exercise", views.toggle_exercise),
    path("complete-workout", views.complete_workout),
    path("uncomplete-workout", views.uncomplete_workout),
    path("workout-crowd", views.workout_crowd),
    path("gym-crowd", views.gym_crowd),
    path("scan-barcode", views.scan_barcode),
    path("products", views.products),
    path("save-product", views.save_product),
    path("product-search", views.product_search),
    path("exercise-save", views.exercise_save),
    path("exercise-delete", views.exercise_delete),
    path("block-save", views.block_save),
    path("block-delete", views.block_delete),
    path("log-walking", views.log_walking),
    path("walking", views.walking),
    path("log-sport", views.log_sport),
    path("sport", views.sport),
    path("sport-delete", views.sport_delete),
    path("log-water", views.log_water),
    path("profile", views.profile),
    path("profile-save", views.profile_save),
    path("profile-recalc", views.profile_recalc),
    path("progress", views.progress),
    path("log-body", views.log_body),
    path("prefs-save", views.prefs_save),
    # подписка / платежи (Platega). status/create — под initData (есть tg_user);
    # callback — сервер-сервер, авторизация секретом в middleware (/api/payments/*).
    path("subscription/status", views.subscription_status),
    path("subscription/create", views.subscription_create),
    path("payments/platega/callback", views.payments_platega_callback),
    path("exercises", views.exercises),
    # бот (n8n) сервер-сервер: /api/bot/* — секрет + telegram_id (см. middleware)
    path("bot/plan-apply", views.plan_apply),
    # cron (n8n по расписанию, авторизация по X-Cron-Secret)
    path("cron/morning", views.cron_morning),
    path("cron/meal-reminders", views.cron_meal_reminders),
    path("cron/workout-ping", views.cron_workout_ping),
    path("cron/weekly", views.cron_weekly),
    path("cron/evaluate-day", views.cron_evaluate_day),
    path("cron/refresh-exercises", views.cron_refresh_exercises),
    # reels-конвейер (n8n сервер-сервер): склейка таймлайна в MP4. X-Cron-Secret.
    path("reels/assemble", views.reels_assemble),
]
