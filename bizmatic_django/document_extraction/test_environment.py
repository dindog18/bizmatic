"""Configuration regressions use temporary .env files, never real credentials."""

import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from bizmatic_django import environment
from .services.llm import _env


class ProjectEnvironmentTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env_path = Path(self.directory.name) / ".env"
        self.env_patch = patch.object(environment, "ENV_PATH", self.env_path)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.process_patch = patch.dict(os.environ, {}, clear=True)
        self.process_patch.start()
        self.addCleanup(self.process_patch.stop)

    def load_module(self, name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise AssertionError(f"Unable to load test module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_file_values_and_process_overrides(self):
        self.env_path.write_text(
            'DB_NAME=from_file\nDB_PASSWORD="test # value" # comment\n'
            'export DOC_EXTRACTION_LLM_PROVIDER=ollama\n'
        )
        os.environ["DB_NAME"] = "from_process"
        environment.load_project_env()
        self.assertEqual(environment.get_env("DB_NAME"), "from_process")
        self.assertEqual(environment.get_env("DB_PASSWORD"), "test # value")
        self.assertEqual(_env("DOC_EXTRACTION_LLM_PROVIDER"), "ollama")

    def test_missing_file_uses_environment_or_default(self):
        os.environ["DB_NAME"] = "deployment_database"
        self.assertEqual(environment.get_env("DB_NAME"), "deployment_database")
        self.assertEqual(environment.get_env("MISSING", "fallback"), "fallback")

    def test_settings_select_postgresql_from_file(self):
        self.env_path.write_text(
            'DB_ENGINE=django.db.backends.postgresql\nDB_NAME=test_database\n'
            'DB_HOST=127.0.0.1\nDB_PORT=5432\n'
        )
        settings_path = Path(environment.__file__).with_name("settings.py")
        module = self.load_module("bizmatic_django._test_settings", settings_path)
        self.assertEqual(module.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(module.DATABASES["default"]["NAME"], "test_database")

    def test_settings_respect_ci_database_override(self):
        self.env_path.write_text('DB_ENGINE=django.db.backends.postgresql\nDB_NAME=from_file\n')
        os.environ.update(DB_ENGINE="django.db.backends.sqlite3", DB_NAME=":memory:")
        settings_path = Path(environment.__file__).with_name("settings.py")
        module = self.load_module("bizmatic_django._test_settings", settings_path)
        self.assertEqual(module.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(module.DATABASES["default"]["NAME"], ":memory:")

    def test_runserver_loads_file_before_debug_default(self):
        self.env_path.write_text("DJANGO_DEBUG=False\n")
        manage_path = Path(environment.__file__).parent.parent / "manage.py"
        manage = self.load_module("_test_manage", manage_path)
        with patch.object(manage.sys, "argv", ["manage.py", "runserver"]):
            with patch("django.core.management.execute_from_command_line"):
                manage.main()
        self.assertEqual(os.environ["DJANGO_DEBUG"], "False")

    def test_storage_service_can_read_file_without_django_startup(self):
        # A standalone service must use the same configuration as Django.
        self.env_path.write_text('LOCAL_FILE_STORAGE_PATH="/tmp/test uploads"\n')
        from .services.storage import get_env

        self.assertEqual(get_env("LOCAL_FILE_STORAGE_PATH"), "/tmp/test uploads")

    def test_container_mode_does_not_load_native_environment(self):
        self.env_path.write_text('LOCAL_ONLY_VALUE=private-native-setting\n')
        os.environ['BIZMATIC_LOAD_PROJECT_ENV'] = 'false'
        environment.load_project_env()
        self.assertNotIn('LOCAL_ONLY_VALUE', os.environ)
