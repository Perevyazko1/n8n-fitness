from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0006_walkinglog_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="workoutcatalog",
            name="kcal_override",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
