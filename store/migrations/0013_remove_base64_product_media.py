from django.db import migrations


def remove_base64_media(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    ProductMedia = apps.get_model("store", "ProductMedia")

    Product.objects.filter(image_data__startswith="data:").update(image_data=None)
    ProductMedia.objects.filter(data_url__startswith="data:").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0012_alter_product_category_alter_product_cloth_type_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_base64_media, migrations.RunPython.noop),
    ]
