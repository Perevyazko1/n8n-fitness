from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0009_bot_daily_limit_botusage"),
    ]

    operations = [
        migrations.AddField(
            model_name="foodlog",
            name="grams",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
