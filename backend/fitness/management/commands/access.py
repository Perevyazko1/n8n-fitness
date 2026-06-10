"""Управление доступом владельцем (на VPS):
  python manage.py access --list                      # последние юзеры + флаги
  python manage.py access <telegram_id> --bot on      # выдать доступ к AI-боту
  python manage.py access <telegram_id> --app off     # забанить в приложении
Приложение открыто всем (approved=True по умолчанию); --app off = бан-рычаг.
"""
from django.core.management.base import BaseCommand

from fitness.models import TgUser


class Command(BaseCommand):
    help = "Доступ к приложению (approved) и к AI-боту (has_bot_access)."

    def add_arguments(self, parser):
        parser.add_argument("telegram_id", nargs="?", type=int, help="telegram_id юзера")
        parser.add_argument("--app", choices=["on", "off"], help="доступ к приложению")
        parser.add_argument("--bot", choices=["on", "off"], help="доступ к AI-боту")
        parser.add_argument("--list", action="store_true", help="показать последних юзеров")

    def handle(self, *args, **o):
        if o["list"]:
            self.stdout.write(f"{'telegram_id':<13} {'name':<18}  app  bot")
            for u in TgUser.objects.order_by("-created_at")[:30]:
                self.stdout.write(
                    f"{u.telegram_id:<13} {(u.first_name or '')[:18]:<18}  "
                    f"{'on ' if u.approved else 'off'}  {'on' if u.has_bot_access else 'off'}"
                )
            return

        tid = o["telegram_id"]
        if not tid:
            self.stderr.write("укажи telegram_id или --list")
            return
        try:
            u = TgUser.objects.get(telegram_id=tid)
        except TgUser.DoesNotExist:
            self.stderr.write(f"юзер {tid} не найден — пусть сначала откроет приложение")
            return

        if o["app"]:
            u.approved = (o["app"] == "on")
        if o["bot"]:
            u.has_bot_access = (o["bot"] == "on")
        if not o["app"] and not o["bot"]:
            self.stdout.write(f"{tid}: app={'on' if u.approved else 'off'} "
                              f"bot={'on' if u.has_bot_access else 'off'} (без изменений; задай --app/--bot)")
            return
        u.save()
        self.stdout.write(self.style.SUCCESS(
            f"OK: {tid} app={'on' if u.approved else 'off'} bot={'on' if u.has_bot_access else 'off'}"
        ))
