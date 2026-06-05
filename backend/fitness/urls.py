from django.urls import path

from . import views

# Пути совпадают с прежними n8n-вебхуками (минус префикс /webhook → /api).
urlpatterns = [
    path("health", views.health),
    path("dashboard", views.dashboard),
    path("food-log", views.food_log),
    path("delete-food", views.delete_food),
    path("repeat-food", views.repeat_food),
    path("workout-today", views.workout_today),
    path("toggle-exercise", views.toggle_exercise),
    path("complete-workout", views.complete_workout),
    path("scan-barcode", views.scan_barcode),
    path("products", views.products),
    path("save-product", views.save_product),
]
