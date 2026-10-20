from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0007_alter_shoporder_options_shoporder_remarks_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="size_stock",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
