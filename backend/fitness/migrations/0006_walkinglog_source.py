from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0005_tguser_bot_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="walkinglog",
            name="source",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
