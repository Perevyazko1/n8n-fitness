from django.db import migrations, models


def approve_existing(apps, schema_editor):
    # существующие пользователи (на момент миграции) — уже свои, открываем доступ
    apps.get_model("fitness", "TgUser").objects.all().update(approved=True)


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tguser",
            name="approved",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(approve_existing, migrations.RunPython.noop),
    ]
