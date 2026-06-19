from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0007_workoutcatalog_kcal_override"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="notifications_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="theme",
            field=models.CharField(blank=True, default="light", max_length=8),
        ),
    ]
