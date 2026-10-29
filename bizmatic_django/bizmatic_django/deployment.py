"""Container startup checks; never rotate a credential key to make startup pass."""
import time
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection, OperationalError


def validate_configuration():
    if settings.DEBUG:
        raise ImproperlyConfigured('Docker deployment requires DJANGO_DEBUG=False.')
    if len(settings.SECRET_KEY) < 50 or settings.SECRET_KEY.startswith(('django-insecure-', 'replace-')):
        raise ImproperlyConfigured('Generate a unique DJANGO_SECRET_KEY with deploy/configure.py.')
    if not settings.ALLOWED_HOSTS or '*' in settings.ALLOWED_HOSTS:
        raise ImproperlyConfigured('Set explicit DJANGO_ALLOWED_HOSTS for this server.')


def ensure_credential_key():
    from db_extraction.credentials import credential_key_path
    from db_extraction.models import DatabaseSource
    path = credential_key_path()
    # Empty-password lookup needs no key. Fetching nonempty password values
    # below deliberately exercises field decryption with the original key.
    if not path.exists() and DatabaseSource.objects.exclude(password='').exists():
        raise ImproperlyConfigured('Saved source credentials exist but their key is missing. Restore the original db-extraction.key into the credential_key volume; do not generate a replacement.')
    call_command('init_db_credential_key')
    for _password in DatabaseSource.objects.values_list('password', flat=True).iterator():
        pass


def prepare_application():
    validate_configuration()
    for attempt in range(30):
        try:
            connection.ensure_connection()
            break
        except OperationalError:
            connection.close()
            if attempt == 29:
                raise RuntimeError('Application database did not become ready within 60 seconds.') from None
            print('Waiting for the application database...', flush=True)
            time.sleep(2)
    Path(settings.LOCAL_FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    call_command('migrate', interactive=False)
    ensure_credential_key()
    call_command('collectstatic', interactive=False)
    call_command('check')
