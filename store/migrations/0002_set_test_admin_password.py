from django.contrib.auth.hashers import make_password
from django.db import migrations


def set_test_admin_password(apps, schema_editor):
    AdminAccount = apps.get_model("store", "AdminAccount")
    AdminAccount.objects.using(schema_editor.connection.alias).filter(username="test").update(
        password_hash=make_password("test")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(set_test_admin_password, migrations.RunPython.noop),
    ]
