import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0012_bodyparams_measurements"),
    ]

    operations = [
        migrations.CreateModel(
            name="WaterLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("ml", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="water_log", to="fitness.tguser")),
            ],
            options={
                "unique_together": {("user", "date")},
            },
        ),
    ]
