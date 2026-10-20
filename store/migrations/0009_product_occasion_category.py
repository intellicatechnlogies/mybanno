from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0008_product_size_stock"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="occasion_category",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
