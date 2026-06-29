"""
Клиент платёжного провайдера Platega (заготовка).

Документация: POST {base}{PROCESS_PATH} — создаёт транзакцию с заданным методом
оплаты (paymentMethod) и возвращает ссылку (redirect) на платёжную страницу.
ID транзакции генерит провайдер (поле id НЕ передаём).

Сейчас используем метод-эндпоинт с paymentMethod (по умолчанию СБП=2), но код принимает
любой код из PAYMENT_METHODS — задел под ЕРИП/карту/межд./крипту без правок.

HTTP — через urllib (как остальной бэк, без зависимости requests). Пока в .env нет
PLATEGA_MERCHANT_ID/PLATEGA_SECRET — configured() == False, и платежи не вызываются.

TODO (уточнить у менеджера Platega):
  - реальный host API (PLATEGA_API_BASE) и путь (PLATEGA_PROCESS_PATH);
  - amount в рублях или копейках;
  - формат подписи входящего колбэка о статусе (сейчас авторизуем общим секретом).
"""
import json
import urllib.error
import urllib.request

from django.conf import settings

# Коды способов оплаты Platega (paymentMethod). Сейчас включён только СБП.
PAYMENT_METHODS = {
    "sbp": 2,       # СБП (QR-код)
    "erip": 3,      # ЕРИП
    "card": 11,     # карточный эквайринг
    "intl": 12,     # международная оплата
    "crypto": 13,   # криптовалюта
}
DEFAULT_METHOD = 2  # СБП


class PlategaError(Exception):
    pass


def configured():
    """Платежи включены, только если заданы и MerchantId, и Secret."""
    return bool(settings.PLATEGA_MERCHANT_ID and settings.PLATEGA_SECRET)


def resolve_method(value, default=None):
    """Привести метод к коду Platega: int (2/3/11/12/13) или строку-алиас (sbp/card/…)."""
    if default is None:
        default = getattr(settings, "SUBSCRIPTION_PAYMENT_METHOD", DEFAULT_METHOD)
    if value in (None, ""):
        return int(default)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in PAYMENT_METHODS:
            return PAYMENT_METHODS[v]
        if v.isdigit():
            return int(v)
        return int(default)
    return int(value)


def pay_link(res):
    """Ссылка на оплату из ответа провайдера: метод-эндпоинт отдаёт `redirect`,
    методless — `url`. Берём что есть."""
    return (res or {}).get("redirect") or (res or {}).get("url") or ""


def create_transaction(*, amount, currency, description, return_url, failed_url,
                       payload, user_id, user_name="", payment_method=None, timeout=15):
    """Создать транзакцию и получить ссылку на оплату. Возвращает распарсенный JSON
    провайдера: {paymentMethod, transactionId, redirect, status, expiresIn, ...}."""
    if not configured():
        raise PlategaError("not_configured")

    method = resolve_method(payment_method)
    # Форма тела — по cURL-примеру из доки (paymentMethod + paymentDetails{amount,currency},
    # остальное верхним уровнем). metadata.userId нужен антифроду — шлём Telegram ID.
    body = {
        "paymentMethod": method,
        "paymentDetails": {"amount": amount, "currency": currency},
        "description": description,
        "return": return_url,
        "failedUrl": failed_url,
        "payload": payload,
        "metadata": {"userId": str(user_id), "userName": user_name or ""},
    }
    url = settings.PLATEGA_API_BASE.rstrip("/") + settings.PLATEGA_PROCESS_PATH
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-MerchantId": settings.PLATEGA_MERCHANT_ID,
            "X-Secret": settings.PLATEGA_SECRET,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise PlategaError(f"http {e.code}: {detail}")
    except Exception as e:  # noqa: BLE001 — сеть/таймаут/парсинг → единый тип ошибки
        raise PlategaError(str(e))
