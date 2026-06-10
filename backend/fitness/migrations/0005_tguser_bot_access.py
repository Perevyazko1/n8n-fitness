from django.db import migrations, models

OWNER_TELEGRAM_ID = 648226895


def open_app_and_grant_owner(apps, schema_editor):
    TgUser = apps.get_model("fitness", "TgUser")
    # приложение теперь открыто всем — снимаем возможный бан со всех существующих
    TgUser.objects.all().update(approved=True)
    # владельцу сразу выдаём доступ к AI-боту
    TgUser.objects.filter(telegram_id=OWNER_TELEGRAM_ID).update(has_bot_access=True)


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0004_streak_level_score"),
    ]

    operations = [
        migrations.AddField(
            model_name="tguser",
            name="has_bot_access",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="tguser",
            name="approved",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(open_app_and_grant_owner, migrations.RunPython.noop),
    ]
