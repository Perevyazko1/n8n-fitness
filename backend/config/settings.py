"""
Django settings — фитнес-API (Mini App backend).
Основа — stateless JSON-API: авторизация по Telegram initData (см. fitness/middleware.py).
Поверх него подключена стандартная Django-админка (/admin/) для просмотра/правки данных
владельцем — со своими сессиями/CSRF/паролем суперюзера (на /api/ это не влияет).
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

# Источник справочника упражнений (курированный RU-JSON в публичном фронт-репо, отдаётся
# GitHub Pages). Крон /api/cron/refresh-exercises фетчит его и апсертит ExerciseLibrary.
EXERCISES_SOURCE_URL = env(
    "EXERCISES_SOURCE_URL",
    "https://perevyazko1.github.io/n8n-fitness-scan/data/exercises_ru.json",
)

# --- Платежи (Platega) — заготовка под оплату подписки --------------------
# Пока MERCHANT_ID/SECRET пустые — платежи ВЫКЛЮЧЕНЫ и приложение работает
# по флагу TgUser.has_bot_access (как сейчас). Заполнишь .env → включится.
PLATEGA_API_BASE = env("PLATEGA_API_BASE", "https://app.platega.io")   # TODO: уточнить host у менеджера
# Путь создания транзакции. Метод-эндпоинт (с paymentMethod) — "/transaction/process";
# у методless-варианта в доке "/v2/transaction/process". Вынесен в env на случай расхождений.
PLATEGA_PROCESS_PATH = env("PLATEGA_PROCESS_PATH", "/transaction/process")
PLATEGA_MERCHANT_ID = env("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = env("PLATEGA_SECRET", "")
# Секрет входящего колбэка о статусе платежа (/api/payments/*): сервер-сервер,
# без initData. TODO: заменить на проверку подписи Platega, когда менеджер
# пришлёт её формат (сейчас — общий секрет в заголовке X-Platega-Secret).
PLATEGA_CALLBACK_SECRET = env("PLATEGA_CALLBACK_SECRET", "")
# Куда вернуть плательщика после оплаты (страницы Mini App).
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "https://perevyazko1.github.io/n8n-fitness-scan")
# Параметры подписки (цена в рублях, срок в днях). TODO: уточнить, рубли это или
# копейки в amount у Platega — пример в доке (amount:500, RUB) выглядит как рубли.
# Месячный тариф:
SUBSCRIPTION_PRICE_RUB = int(env("SUBSCRIPTION_PRICE_RUB", "299") or 299)
SUBSCRIPTION_DAYS = int(env("SUBSCRIPTION_DAYS", "30") or 30)
# Годовой тариф (в UI Mini App показан 2990 ₽ / 365 дн.). Цена/срок берутся ПО ПЛАНУ,
# чтобы списание совпадало с выбранной карточкой (без этого «Год» списывал бы 299).
SUBSCRIPTION_YEAR_PRICE_RUB = int(env("SUBSCRIPTION_YEAR_PRICE_RUB", "2990") or 2990)
SUBSCRIPTION_YEAR_DAYS = int(env("SUBSCRIPTION_YEAR_DAYS", "365") or 365)
# Способ оплаты по умолчанию (Platega paymentMethod). Сейчас только СБП(2), но
# код принимает и другие (3=ЕРИП, 11=карта, 12=межд., 13=крипта) — см. platega.PAYMENT_METHODS.
SUBSCRIPTION_PAYMENT_METHOD = int(env("SUBSCRIPTION_PAYMENT_METHOD", "2") or 2)
# Рубильник кнопки подписки в Mini App: "0" → кнопка неактивна («Скоро») ДАЖЕ при
# заданных ключах Platega. Удобно включать/выключать оплату из .env без правок кода.
# По умолчанию включено (если ключи заданы). Выключить: SUBSCRIPTION_ENABLED=0
SUBSCRIPTION_ENABLED = (env("SUBSCRIPTION_ENABLED", "1") or "1").strip().lower() \
    not in ("0", "false", "no", "off", "")

INSTALLED_APPS = [
    # contrib — нужны для веб-админки (/admin/)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "fitness",
]

# ApiMiddleware — первой: для /api/ делает initData-auth + CORS, для остального
# (в т.ч. /admin/ и /django-static/) просто пропускает запрос дальше по цепочке.
# Ниже — стандартный стек Django, нужный админке (сессии/CSRF/auth) и отдаче статики.
MIDDLEWARE = [
    "fitness.middleware.ApiMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
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

# --- Статика админки ---
# Отдельный префикс /django-static/ — чтобы не пересекаться с путями n8n на том же
# домене. WhiteNoise отдаёт собранную статику (collectstatic делается при старте).
STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Админка за nginx-проксёй (HTTPS терминируется на nginx) ---
# nginx шлёт X-Forwarded-Proto=https → Django считает запрос защищённым
# (нужно для secure-cookie и редиректов админки).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = ["https://" + h for h in ALLOWED_HOSTS if h not in ("*", "127.0.0.1", "localhost")]
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
# свои имена кук — чтобы не пересекаться с куками n8n на том же домене
SESSION_COOKIE_NAME = "fitadmin_sessionid"
CSRF_COOKIE_NAME = "fitadmin_csrftoken"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
