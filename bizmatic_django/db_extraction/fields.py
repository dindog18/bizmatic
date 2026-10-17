"""Model field that keeps PostgreSQL passwords encrypted in database storage."""

from django.db import models

from .credentials import decrypt_password, encrypt_password


class EncryptedPasswordField(models.TextField):
    """Expose plaintext to the application; encrypt values written by the ORM.

    Password lookup/filtering is intentionally unsupported because encryption
    generates a fresh token on every write. Never use passwords as identifiers.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return None if value is None else encrypt_password(value)

    @staticmethod
    def from_db_value(value, _expression, _connection):
        return None if value is None else decrypt_password(value)

    def value_to_string(self, obj):
        # Prevent plaintext exports and ambiguous ciphertext fixture imports.
        raise ValueError("Source credentials cannot be serialized as fixtures. Use an encrypted database backup.")
