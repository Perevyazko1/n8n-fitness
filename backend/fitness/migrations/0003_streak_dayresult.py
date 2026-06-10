from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0002_tguser_approved"),
    ]

    operations = [
        migrations.CreateModel(
            name="Streak",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("nutrition", "Питание"), ("workout", "Тренировки")], max_length=16)),
                ("current", models.IntegerField(default=0)),
                ("longest", models.IntegerField(default=0)),
                ("misses_in_row", models.IntegerField(default=0)),
                ("status", models.CharField(choices=[("active", "active"), ("frozen", "frozen"), ("reset", "reset")], default="active", max_length=8)),
                ("last_ok_date", models.DateField(blank=True, null=True)),
                ("last_eval_date", models.DateField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="streaks", to="fitness.tguser")),
            ],
            options={
                "unique_together": {("user", "kind")},
            },
        ),
        migrations.CreateModel(
            name="DayResult",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("nutrition_ok", models.BooleanField(blank=True, null=True)),
                ("workout_ok", models.BooleanField(blank=True, null=True)),
                ("evaluated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="day_results", to="fitness.tguser")),
            ],
            options={
                "unique_together": {("user", "date")},
            },
        ),
        migrations.AddIndex(
            model_name="dayresult",
            index=models.Index(fields=["user", "date"], name="dayresult_user_date_idx"),
        ),
    ]
