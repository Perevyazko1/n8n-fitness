import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0008_profile_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="tguser",
            name="bot_daily_limit",
            field=models.IntegerField(default=5),
        ),
        migrations.CreateModel(
            name="BotUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("count", models.IntegerField(default=0)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bot_usage", to="fitness.tguser")),
            ],
            options={
                "unique_together": {("user", "date")},
            },
        ),
        migrations.AddIndex(
            model_name="botusage",
            index=models.Index(fields=["user", "date"], name="fitness_bot_user_id_date_idx"),
        ),
    ]
