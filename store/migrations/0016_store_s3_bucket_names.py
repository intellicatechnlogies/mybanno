import json
from pathlib import Path

from django.conf import settings
from django.db import migrations

from store.credential_crypto import encrypt_credential_value


def store_bucket_names(apps, schema_editor):
    path = Path(settings.BASE_DIR) / "aws.json"
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    Credential = apps.get_model("store", "Credential")
    bucket_map = {
        "productimage": str(data.get("Clothimg_bucket") or "").strip(),
        "dbbackup": str(data.get("Bucket") or "").strip(),
    }
    for account, bucket_name in bucket_map.items():
        if not bucket_name:
            continue
        Credential.objects.update_or_create(
            service="AWS",
            account=account,
            credential_type="bucket_name",
            defaults={
                "description": f"S3 bucket name for {account}",
                "encrypted_value": encrypt_credential_value(bucket_name),
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0015_move_aws_credentials_to_table"),
    ]

    operations = [
        migrations.RunPython(store_bucket_names, migrations.RunPython.noop),
    ]
