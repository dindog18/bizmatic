"""Deployment regressions use isolated keys and synthetic source credentials."""
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, override_settings

from bizmatic_django.deployment import ensure_credential_key, validate_configuration
from db_extraction.models import DatabaseSource


class DeploymentKeyTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.key = Path(temporary.name) / 'keys' / 'db-extraction.key'
        settings = override_settings(DB_EXTRACTION_CREDENTIAL_KEY_FILE=self.key)
        settings.enable(); self.addCleanup(settings.disable)

    def provision(self):
        with redirect_stdout(io.StringIO()):
            ensure_credential_key()

    def source(self):
        DatabaseSource.objects.create(name='Deployment fixture', host='example.test',
            database_name='fixture', username='reader', password='synthetic-source-password')

    def test_first_start_provisions_and_restart_keeps_key(self):
        self.provision()
        original = self.key.read_bytes()
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        self.source(); self.provision()
        self.assertEqual(self.key.read_bytes(), original)

    def test_missing_key_for_existing_credentials_is_not_replaced(self):
        self.provision(); self.source(); self.key.unlink()
        with self.assertRaisesMessage(ImproperlyConfigured, 'Restore the original'):
            self.provision()
        self.assertFalse(self.key.exists())

    def test_wrong_key_fails_without_rotating_it(self):
        self.provision(); self.source()
        replacement = Fernet.generate_key()
        self.key.write_bytes(replacement)
        with self.assertRaisesMessage(ImproperlyConfigured, 'matching credential key'):
            self.provision()
        self.assertEqual(self.key.read_bytes(), replacement)

    def test_health_reports_readiness_without_database_details(self):
        self.assertEqual(self.client.get('/healthz/').json(), {'status':'ok'})
        with patch('bizmatic_django.health.connection.cursor', side_effect=DatabaseError('private-database-detail')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status':'unavailable'})
        self.assertNotIn(b'private-database-detail', response.content)
        self.assertEqual(self.client.post('/healthz/').status_code, 405)


class DeploymentConfigurationTests(SimpleTestCase):
    def test_unsafe_configuration_fails_early(self):
        cases = [dict(DEBUG=True, SECRET_KEY='a'*64, ALLOWED_HOSTS=['localhost']),
                 dict(DEBUG=False, SECRET_KEY='replace-me', ALLOWED_HOSTS=['localhost']),
                 dict(DEBUG=False, SECRET_KEY='a'*64, ALLOWED_HOSTS=['*'])]
        for values in cases:
            with self.subTest(values=list(values)), override_settings(**values):
                with self.assertRaises(ImproperlyConfigured):
                    validate_configuration()
        with override_settings(DEBUG=False, SECRET_KEY='a'*64, ALLOWED_HOSTS=['localhost']):
            validate_configuration()

    def test_configuration_generator_does_not_overwrite_or_print_secrets(self):
        path = Path(__file__).resolve().parents[2] / 'deploy' / 'configure.py'
        # The container intentionally omits the host-only configuration template.
        if not (path.parent.parent / '.env.docker.example').exists():
            self.skipTest('Host configuration generator runs outside the container.')
        spec = importlib.util.spec_from_file_location('deployment_configure', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with TemporaryDirectory() as folder:
            output = Path(folder) / '.env.docker'
            module.configure(output, '192.0.2.10', 8005, database_file=Path(folder)/'data/app.sqlite3', uploads_dir=Path(folder)/'uploads', key_dir=Path(folder)/'keys')
            original = output.read_text()
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertIn('192.0.2.10', original)
            self.assertNotIn('replace-with-generated', original)
            with self.assertRaises(FileExistsError):
                module.configure(output, 'localhost', 8006)
            self.assertEqual(output.read_text(), original)
            with self.assertRaises(ValueError):
                module.configure(Path(folder) / 'bad', 'localhost\nINJECTED=value', 8005)
