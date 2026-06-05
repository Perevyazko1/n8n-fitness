"""
Единая middleware для /api/:
  1. CORS (фронт на github.io — другой origin; POST text/plain → без preflight,
     но ответу нужен Access-Control-Allow-Origin).
  2. Авторизация по Telegram initData (один раз — вместо 7 копий в n8n).
Кладёт в request: .tg_user (TgUser) и .payload (распарсенное тело).
Health-check (/api/health) пропускается без авторизации.
"""
import json

from django.conf import settings
from django.http import JsonResponse

from .auth import AuthError, ensure_user, verify_init_data

OPEN_PATHS = {"/api/health"}


class ApiMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        # CORS preflight (на случай если клиент пришлёт OPTIONS).
        if request.method == "OPTIONS":
            return self._cors(JsonResponse({"ok": True}))

        if request.path in OPEN_PATHS:
            return self._cors(self.get_response(request))

        try:
            body = json.loads(request.body or b"{}")
        except (ValueError, TypeError):
            return self._cors(JsonResponse({"ok": False, "error": "bad_json"}, status=400))

        try:
            tg = verify_init_data(body.get("initData", ""), settings.TELEGRAM_BOT_TOKEN)
        except AuthError as e:
            return self._cors(JsonResponse({"ok": False, "error": "auth: " + str(e)}, status=401))

        request.tg_user = ensure_user(tg)
        request.payload = body
        return self._cors(self.get_response(request))

    @staticmethod
    def _cors(resp):
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
