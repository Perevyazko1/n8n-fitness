from django.db import migrations, models
from django.utils import timezone


def cut_history_for_disabled(apps, schema_editor):
    """Домены, отключённые ДО перехода на пересчёт из истории, обрезаем на сегодня.
    Иначе первый же replay_state поднял бы их старые дни и вернул серию/форму,
    которые пользователь обнулил тумблером."""
    Streak = apps.get_model("fitness", "Streak")
    today = timezone.localdate()
    for s in Streak.objects.select_related("user").all():
        profile = getattr(s.user, "profile", None)
        if not profile:
            continue
        enabled = (profile.nutrition_enabled if s.kind == "nutrition"
                   else profile.workout_enabled)
        if not enabled and s.history_from is None:
            s.history_from = today
            s.save(update_fields=["history_from"])


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0016_workoutlog_crowd"),
    ]

    operations = [
        migrations.AddField(
            model_name="dayresult",
            name="belly_delta",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="streak",
            name="history_from",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(cut_history_for_disabled, migrations.RunPython.noop),
    ]
