"""Offline CLI regressions: no Docker daemon, user data or provider calls."""
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import cli


class CLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patch = patch.object(cli, 'ROOT', self.root); self.patch.start(); self.addCleanup(self.patch.stop)
        self.uid = patch.object(os, 'getuid', return_value=1000); self.uid.start(); self.addCleanup(self.uid.stop)
        self.gid = patch.object(os, 'getgid', return_value=1000); self.gid.start(); self.addCleanup(self.gid.stop)
        (self.root / '.env.docker.example').write_text('''DJANGO_SECRET_KEY=replace-with-generated-secret
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8005,http://127.0.0.1:8005
BIZMATIC_PORT=8005
BIZMATIC_DATA_DIR=__DATA_DIR__
BIZMATIC_DATABASE_FILE=__DATABASE_FILE__
BIZMATIC_UPLOADS_DIR=__UPLOADS_DIR__
BIZMATIC_KEY_DIR=__KEY_DIR__
BIZMATIC_UID=__UID__
BIZMATIC_GID=__GID__
DB_ENGINE=django.db.backends.sqlite3
''')
        self.config = self.root / 'user.env'

    def init(self, **options):
        return cli.create_configuration(self.config, **options)

    def call(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(arguments)

    def test_init_preserves_user_file_and_existing_database_and_key(self):
        data = self.root / 'chosen data'; data.mkdir()
        database = data / 'existing.sqlite3'; database.write_bytes(b'original-db')
        keys = self.root / 'private'; keys.mkdir()
        key = keys / 'db-extraction.key'; key.write_bytes(b'original-key')
        self.init(database_file=database, key_dir=keys, uploads_dir=self.root / 'originals')
        values = cli.read_config(self.config)
        self.assertEqual(values['BIZMATIC_DATABASE_FILE'], str(database.resolve()))
        self.assertEqual(values['BIZMATIC_KEY_DIR'], str(keys.resolve()))
        self.assertEqual(values['DB_ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(database.read_bytes(), b'original-db')
        self.assertEqual(key.read_bytes(), b'original-key')
        original = self.config.read_text()
        with self.assertRaises(FileExistsError): self.init()
        self.assertEqual(self.config.read_text(), original)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    @patch('deploy.cli.shutil.which', return_value='/usr/bin/docker')
    @patch('deploy.cli.subprocess.run')
    def test_start_builds_sqlite_and_stop_never_deletes_data(self, run, _which):
        self.init()
        self.assertEqual(self.call(['start','--env-file',str(self.config)]), 0)
        command = run.call_args.args[0]
        self.assertIn('up', command); self.assertIn('--build', command)
        self.assertNotIn(str(self.root / 'compose.postgres.yaml'), command)
        self.assertEqual(self.call(['stop','--env-file',str(self.config)]), 0)
        self.assertEqual(run.call_args.args[0][-1], 'stop')
        self.assertNotIn('down', run.call_args.args[0])

    @patch('deploy.cli.shutil.which', return_value='/usr/bin/docker')
    @patch('deploy.cli.subprocess.run')
    def test_dev_mode_is_remembered_for_updates_and_can_be_disabled(self, run, _which):
        self.init()
        self.assertEqual(self.call(['start','--env-file',str(self.config),'--dev']), 0)
        self.assertIn(str(self.root / 'compose.dev.yaml'), run.call_args.args[0])
        self.assertEqual(self.call(['update','--env-file',str(self.config)]), 0)
        self.assertIn(str(self.root / 'compose.dev.yaml'), run.call_args.args[0])
        self.assertEqual(self.call(['update','--env-file',str(self.config),'--production']), 0)
        self.assertNotIn(str(self.root / 'compose.dev.yaml'), run.call_args.args[0])

    @patch('deploy.cli.shutil.which', return_value='/usr/bin/docker')
    @patch('deploy.cli.subprocess.run')
    def test_postgres_is_explicit_and_config_output_excludes_secrets(self, run, _which):
        self.init(database='postgres')
        self.assertEqual(self.call(['start','--env-file',str(self.config)]), 0)
        self.assertIn(str(self.root / 'compose.postgres.yaml'), run.call_args.args[0])
        output = io.StringIO()
        with contextlib.redirect_stdout(output): cli.main(['config','--env-file',str(self.config)])
        values = cli.read_config(self.config)
        self.assertNotIn(values['DJANGO_SECRET_KEY'], output.getvalue())
        self.assertNotIn(values['DB_PASSWORD'], output.getvalue())

    @patch('deploy.cli.subprocess.run')
    def test_native_mode_needs_no_docker_or_docker_configuration(self, run):
        run.return_value.returncode = 0
        self.assertEqual(self.call(['start','--local','--address','127.0.0.1:9000']), 0)
        self.assertEqual(run.call_args.args[0][-3:], ['manage.py','runserver','127.0.0.1:9000'])
        self.assertEqual(self.call(['runserver','127.0.0.1:9001','--noreload']), 0)
        self.assertEqual(run.call_args.args[0][-2:], ['127.0.0.1:9001','--noreload'])

    @patch('deploy.cli.subprocess.run')
    def test_unconfigured_start_and_legacy_storage_refuse_without_running_docker(self, run):
        self.assertEqual(self.call(['start','--env-file',str(self.config)]), 1)
        self.config.write_text('DB_ENGINE=django.db.backends.postgresql\n')
        self.assertEqual(self.call(['start','--env-file',str(self.config)]), 1)
        run.assert_not_called()

    @patch('deploy.cli.shutil.which', return_value='/usr/bin/docker')
    @patch('deploy.cli.subprocess.run', side_effect=subprocess.CalledProcessError(1, ['docker']))
    def test_failed_start_does_not_change_saved_mode(self, _run, _which):
        self.init()
        self.assertEqual(self.call(['start','--env-file',str(self.config),'--dev']), 1)
        self.assertFalse(cli.state_file(self.config).exists())

    def test_invalid_paths_and_environment_assignments_are_rejected(self):
        with self.assertRaises(ValueError): self.init(uploads_dir='/app')
        with self.assertRaises(ValueError): self.init(uploads_dir=self.root/'bizmatic_django/private-uploads')
        with self.assertRaises(ValueError): self.init(key_dir=self.root/'deploy/private-keys')
        with self.assertRaises(ValueError): self.init(host='localhost\nINJECTED=value')
        self.config.write_text('VALUE="quoted"\n')
        with self.assertRaises(ValueError): cli.read_config(self.config)


if __name__ == '__main__':
    unittest.main()
