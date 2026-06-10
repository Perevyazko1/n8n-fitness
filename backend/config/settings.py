"""
Django settings — фитнес-API (Mini App backend).
Минимальный stateless JSON-API: без сессий, без админки, без django.contrib.auth.
Авторизация — по Telegram initData (см. fitness/middleware.py).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None):
    return os.environ.get(key, default)


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

# Токен Telegram-бота — для HMAC-валидации initData мини-аппа.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", "")

# Секрет для cron-эндпоинтов (/api/cron/*): их дёргает n8n-крон без initData,
# авторизация по заголовку X-Cron-Secret. Значение — в .env.
CRON_SECRET = env("CRON_SECRET", "")

INSTALLED_APPS = [
    "fitness",
]

# Только наша middleware: initData-auth + CORS для /api/. Без CSRF/сессий.
MIDDLEWARE = [
    "fitness.middleware.ApiMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "fitness"),
        "USER": env("POSTGRES_USER", "fitness"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = env("TZ", "Europe/Moscow")
USE_I18N = False
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
