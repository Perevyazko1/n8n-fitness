import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fitness", "0010_foodlog_grams"),
    ]

    operations = [
        migrations.AddField(
            model_name="tguser",
            name="subscription_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transaction_id", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("amount", models.IntegerField(default=0)),
                ("currency", models.CharField(default="RUB", max_length=8)),
                ("method", models.IntegerField(default=2)),
                ("status", models.CharField(default="PENDING", max_length=24)),
                ("plan", models.CharField(blank=True, default="", max_length=32)),
                ("payload", models.CharField(blank=True, default="", max_length=255)),
                ("pay_url", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="fitness.tguser")),
            ],
            options={
                "indexes": [models.Index(fields=["user", "status"], name="fitness_pay_user_status_idx")],
            },
        ),
    ]
