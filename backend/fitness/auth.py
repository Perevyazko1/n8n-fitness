"""
Валидация Telegram WebApp initData — порт 1:1 из n8n-ноды `Validate & Parse`.
Схема: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .models import TgUser


class AuthError(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age_sec: int = 86400) -> dict:
    if not init_data:
        raise AuthError("missing initData")
    if not bot_token:
        raise AuthError("bot token not configured")

    # parse_qsl уже делает URL-decode значений (как decodeURIComponent в n8n).
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AuthError("no hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        raise AuthError("invalid signature")

    auth_date = int(pairs.get("auth_date", "0") or "0")
    if max_age_sec and (time.time() - auth_date) > max_age_sec:
        raise AuthError("initData too old")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise AuthError("cannot parse user")
    if not user.get("id"):
        raise AuthError("no user.id")
    return user


def ensure_user(tg_user: dict) -> TgUser:
    obj, _ = TgUser.objects.get_or_create(
        telegram_id=int(tg_user["id"]),
        defaults={"first_name": tg_user.get("first_name", "") or ""},
    )
    return obj
