from django.db import DatabaseError, OperationalError


MEDIA_BUCKET_ACCOUNT = "productimage"
BACKUP_BUCKET_ACCOUNT = "dbbackup"
AWS_SERVICE = "AWS"


class AwsCredentialsError(RuntimeError):
    pass


def get_credential_value(account, credential_type):
    try:
        from .models import Credential

        credential = Credential.objects.filter(
            service=AWS_SERVICE,
            account=account,
            credential_type=credential_type,
        ).first()
    except (DatabaseError, OperationalError):
        return ""
    return credential.plain_value if credential else ""


def get_credential_value_by_service(account, credential_types):
    try:
        from .models import Credential

        for credential_type in credential_types:
            credential = Credential.objects.filter(
                service=AWS_SERVICE,
                account=account,
                credential_type=credential_type,
            ).first()
            if credential:
                return credential.plain_value
    except (DatabaseError, OperationalError):
        return ""
    return ""


def load_aws_config(account):
    account = account.strip()
    if not account:
        raise AwsCredentialsError("AWS credential account is required.")

    access_key = get_credential_value(account, "access_key_id")
    secret_key = get_credential_value(account, "secret_access_key")
    region = get_credential_value(account, "region")
    bucket = get_credential_value(account, "bucket_name")
    if not all((access_key, secret_key, region)):
        raise AwsCredentialsError(
            f"AWS credentials for account '{account}' are incomplete. "
            "Store access_key_id, secret_access_key, and region."
        )
    if not bucket:
        bucket = account
    return {
        "bucket": bucket,
        "region": region,
        "access_key": access_key,
        "secret_key": secret_key,
    }


def load_backup_aws_config():
    bucket = get_credential_value_by_service(
        "production",
        ("dbbackup", "bucket_name"),
    )
    access_key = get_credential_value_by_service(
        "production",
        ("access_key_id", "Access_key_ID"),
    )
    secret_key = get_credential_value_by_service(
        "production",
        ("secret_access_key", "Secret_Access_Key"),
    )
    region = get_credential_value_by_service(
        "production",
        ("region", "Region"),
    )

    if all((bucket, access_key, secret_key, region)):
        return {
            "bucket": bucket,
            "region": region,
            "access_key": access_key,
            "secret_key": secret_key,
        }

    return load_aws_config(BACKUP_BUCKET_ACCOUNT)
