import json
from pathlib import Path

from django.conf import settings
from django.db import migrations

from store.credential_crypto import encrypt_credential_value


def migrate_aws_credentials(apps, schema_editor):
    path = Path(settings.BASE_DIR) / "aws.json"
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    access_key = str(data.get("Access_key_ID") or "").strip()
    secret_key = str(data.get("Secret_Access_Key") or "").strip()
    region = str(data.get("Region") or "").strip()
    if not all((access_key, secret_key, region)):
        return

    Credential = apps.get_model("store", "Credential")
    for account in ("productimage", "dbbackup"):
        bucket_name = (
            str(data.get("Clothimg_bucket") or "").strip()
            if account == "productimage"
            else str(data.get("Bucket") or "").strip()
        )
        for credential_type, value in (
            ("access_key_id", access_key),
            ("secret_access_key", secret_key),
            ("region", region),
            ("bucket_name", bucket_name),
        ):
            Credential.objects.update_or_create(
                service="AWS",
                account=account,
                credential_type=credential_type,
                defaults={
                    "description": f"AWS {credential_type.replace('_', ' ')} for {account}",
                    "encrypted_value": encrypt_credential_value(value),
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0014_credential"),
    ]

    operations = [
        migrations.RunPython(migrate_aws_credentials, migrations.RunPython.noop),
    ]
