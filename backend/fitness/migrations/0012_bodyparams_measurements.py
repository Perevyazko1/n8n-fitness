from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0011_payments"),
    ]

    operations = [
        migrations.AddField(
            model_name="bodyparams",
            name="waist",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bodyparams",
            name="chest",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bodyparams",
            name="hips",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bodyparams",
            name="biceps",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bodyparams",
            name="thigh",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
