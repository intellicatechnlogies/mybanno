from django.db import migrations

from store.credential_crypto import encrypt_credential_value


def set_dbbackup_bucket(apps, schema_editor):
    Credential = apps.get_model("store", "Credential")
    encrypted_bucket = encrypt_credential_value("mybannodbbackup")

    Credential.objects.filter(
        service="AWS",
        account="production",
        credential_type="dbbackup",
    ).update(encrypted_value=encrypted_bucket)

    Credential.objects.update_or_create(
        service="AWS",
        account="dbbackup",
        credential_type="bucket_name",
        defaults={
            "description": "S3 bucket name for dbbackup",
            "encrypted_value": encrypted_bucket,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0016_store_s3_bucket_names"),
    ]

    operations = [
        migrations.RunPython(set_dbbackup_bucket, migrations.RunPython.noop),
    ]
