import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def get_credential_fernet():
    key = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        derived = hashlib.sha256(str(key).encode()).digest()
        return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_credential_value(value):
    return get_credential_fernet().encrypt(str(value).encode("utf-8"))


def decrypt_credential_value(encrypted_value):
    if not encrypted_value:
        return ""
    try:
        return get_credential_fernet().decrypt(encrypted_value).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
