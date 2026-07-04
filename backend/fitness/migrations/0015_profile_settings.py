from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0014_exerciselibrary"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="nutrition_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="workout_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="include_activity_kcal",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="calorie_formula",
            field=models.CharField(blank=True, default="mifflin", max_length=16),
        ),
    ]
