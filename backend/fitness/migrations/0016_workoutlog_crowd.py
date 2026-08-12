"""Загруженность зала: тумблер «много людей» + время окончания тренировки.

Пишется из Mini App при «Завершить тренировку», читается экраном статистики
(/api/gym-crowd), который агрегирует отметки по (день недели × 2-часовой слот).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0015_profile_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="workoutlog",
            name="crowd",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workoutlog",
            name="logged_time",
            field=models.TimeField(blank=True, null=True),
        ),
    ]
