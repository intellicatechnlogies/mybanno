from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


def populate_order_numbers(apps, schema_editor):
    ShopOrder = apps.get_model("store", "ShopOrder")
    for order in ShopOrder.objects.filter(order_number__isnull=True).iterator():
        while True:
            number = "MB-" + uuid.uuid4().hex[:12].upper()
            if not ShopOrder.objects.filter(order_number=number).exists():
                order.order_number = number
                order.save(update_fields=["order_number"])
                break


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0017_set_dbbackup_bucket_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(max_length=100)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("mobile_number", models.CharField(max_length=10, unique=True)),
                ("password_hash", models.CharField(max_length=512)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        migrations.AddField(
            model_name="shoporder",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="orders", to="store.customer"),
        ),
        migrations.AddField(
            model_name="shoporder",
            name="order_number",
            field=models.CharField(blank=True, editable=False, max_length=32, null=True, unique=True),
        ),
        migrations.RunPython(populate_order_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="shoporder",
            name="order_number",
            field=models.CharField(editable=False, max_length=32, unique=True),
        ),
    ]
