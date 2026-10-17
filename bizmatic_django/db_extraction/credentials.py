"""Encrypt source credentials with a key kept outside the application database."""

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


PASSWORD_PREFIX = "fernet:v1:"


def credential_key_path() -> Path:
    return Path(settings.DB_EXTRACTION_CREDENTIAL_KEY_FILE).expanduser()


def credential_cipher() -> Fernet:
    """Load a provisioned key; a missing key must never be silently replaced."""
    try:
        descriptor = os.open(credential_key_path(), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as key_file:
            metadata = os.fstat(key_file.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ImproperlyConfigured("The credential key must be a regular file with permissions 0600.")
            key = key_file.read().strip()
        return Fernet(key)
    except (OSError, ValueError) as error:
        raise ImproperlyConfigured(
            "The database credential key is missing or invalid. Provision it with "
            "'python manage.py init_db_credential_key' or restore the original key backup."
        ) from error


def encrypt_password(value: str) -> str:
    """Encrypt every nonempty plaintext value, including values resembling tokens."""
    if not value:
        return ""
    return PASSWORD_PREFIX + credential_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_password(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(PASSWORD_PREFIX):
        raise ImproperlyConfigured("A source password is not encrypted. Apply the database extraction migrations.")
    try:
        return credential_cipher().decrypt(value[len(PASSWORD_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as error:
        raise ImproperlyConfigured(
            "A database credential cannot be decrypted. Restore the matching credential key and database backup."
        ) from error
