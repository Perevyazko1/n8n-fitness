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
    # cron (n8n по расписанию, авторизация по X-Cron-Secret)
    path("cron/meal-reminders", views.cron_meal_reminders),
    path("cron/evaluate-day", views.cron_evaluate_day),
]
