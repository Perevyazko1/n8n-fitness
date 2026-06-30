from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0013_waterlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExerciseLibrary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("section", models.CharField(blank=True, default="", max_length=32)),
                ("muscle_group", models.CharField(blank=True, default="", max_length=64)),
                ("equipment", models.CharField(blank=True, default="", max_length=128)),
                ("sets", models.CharField(blank=True, default="", max_length=16)),
                ("reps", models.CharField(blank=True, default="", max_length=32)),
                ("met", models.FloatField(blank=True, null=True)),
                ("default_min", models.IntegerField(blank=True, null=True)),
                ("cue", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
