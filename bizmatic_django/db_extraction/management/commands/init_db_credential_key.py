"""Provision the encryption key for this application service account once."""

import os

from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand, CommandError

from ...credentials import credential_cipher, credential_key_path


class Command(BaseCommand):
    help = "Create the database credential encryption key without overwriting an existing key."

    def handle(self, *args, **options):
        path = credential_key_path()
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            credential_cipher()
            self.stdout.write("An existing credential key was verified and kept.")
            return
        except OSError as error:
            raise CommandError("Could not create the credential key file.") from error

        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(Fernet.generate_key())
            key_file.flush()
            os.fsync(key_file.fileno())
        self.stdout.write(self.style.SUCCESS(f"Credential key created at {path}. Back it up securely."))
