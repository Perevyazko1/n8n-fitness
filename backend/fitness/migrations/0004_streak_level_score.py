from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0003_streak_dayresult"),
    ]

    operations = [
        migrations.AddField(
            model_name="streak",
            name="level_score",
            field=models.IntegerField(default=50),
        ),
    ]
