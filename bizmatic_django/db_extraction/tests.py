"""Credential storage and snapshot integrity regression checks."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core import serializers
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import Model
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from .admin import DatabaseSourceForm
from .credentials import PASSWORD_PREFIX, decrypt_password
from .models import DatabaseConstraint, DatabaseSchema, DatabaseSource, DatabaseTable, ExtractionRun


class CredentialStorageTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.key_path = Path(directory.name) / "credentials.key"
        override = self.settings(DB_EXTRACTION_CREDENTIAL_KEY_FILE=self.key_path)
        override.enable()
        self.addCleanup(override.disable)
        call_command("init_db_credential_key", stdout=StringIO())
        self.source = DatabaseSource.objects.create(
            name="Example", host="localhost", database_name="metadata",
            username="metadata_reader", password="test-password",
        )

    def stored_password(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT password FROM db_extraction_databasesource WHERE id = %s", [self.source.pk])
            return cursor.fetchone()[0]

    def test_password_is_encrypted_and_orm_updates_remain_encrypted(self):
        first_token = self.stored_password()
        self.assertTrue(first_token.startswith(PASSWORD_PREFIX))
        self.assertNotIn("test-password", first_token)
        self.source.refresh_from_db()
        self.assertEqual(self.source.password, "test-password")
        DatabaseSource.objects.filter(pk=self.source.pk).update(password="replacement")
        self.assertEqual(decrypt_password(self.stored_password()), "replacement")
        self.source.refresh_from_db()
        self.source.save()
        self.assertNotEqual(self.stored_password(), first_token)
        self.assertEqual(decrypt_password(self.stored_password()), "replacement")

    def test_key_provisioning_preserves_existing_key(self):
        original_key = self.key_path.read_bytes()
        call_command("init_db_credential_key", stdout=StringIO())
        self.assertEqual(self.key_path.read_bytes(), original_key)
        self.assertEqual(self.key_path.stat().st_mode & 0o777, 0o600)

    def test_missing_wrong_and_insecure_keys_fail_without_exposing_password(self):
        token = self.stored_password()
        key = self.key_path.read_bytes()
        self.key_path.unlink()
        with self.assertRaises(ImproperlyConfigured):
            decrypt_password(token)
        self.key_path.write_bytes(Fernet.generate_key())
        self.key_path.chmod(0o600)
        with self.assertRaises(ImproperlyConfigured):
            decrypt_password(token)
        self.key_path.write_bytes(key)
        self.key_path.chmod(0o644)
        with self.assertRaises(ImproperlyConfigured):
            decrypt_password(token)

    def test_admin_preserves_replaces_and_clears_password_without_rendering_it(self):
        data = dict(name="Example", host="localhost", port=5432,
                    database_name="metadata", username="metadata_reader", ssl_mode="prefer",
                    connect_timeout=10, enabled=True, included_schemas="")
        verifier = patch("db_extraction.forms.test_connection", return_value={"server_version": "17", "schema_count": 1})
        verifier.start()
        self.addCleanup(verifier.stop)
        for password, clear, expected in [("", False, "test-password"), ("new-secret", False, "new-secret"), ("", True, "")]:
            form = DatabaseSourceForm(
                data={**data, "password": password, "clear_password": clear},
                instance=DatabaseSource.objects.get(pk=self.source.pk),
            )
            self.assertTrue(form.is_valid(), form.errors.as_json())
            form.save()
            self.assertEqual(decrypt_password(self.stored_password()), expected)
        rendered = str(DatabaseSourceForm(instance=self.source)["password"])
        self.assertNotIn("test-password", rendered)

    def test_fixture_export_does_not_expose_decrypted_password(self):
        with self.assertRaisesMessage(ValueError, "cannot be serialized"):
            serializers.serialize("json", [self.source])

    @patch("db_extraction.forms.test_connection")
    def test_changed_connection_cannot_reuse_saved_password(self, verify):
        data = dict(name="Example", host="localhost", port=5432, database_name="metadata",
                    username="metadata_reader", password="", ssl_mode="prefer", ssl_root_cert="",
                    connect_timeout=10, enabled=True, included_schemas="")
        changes = {"host": ["other-host", "localhost,other-host", "/tmp/other-postgres"],
                   "port": [5433], "database_name": ["other", "postgresql://other-host/other"],
                   "username": ["other_reader"], "ssl_mode": ["disable", "verify-full"],
                   "ssl_root_cert": ["/tmp/other-ca.pem"]}
        for field, values in changes.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    form = DatabaseSourceForm(data={**data, field: value},
                                              instance=DatabaseSource.objects.get(pk=self.source.pk))
                    self.assertFalse(form.is_valid())
                    self.assertIn("password", form.errors)
                    verify.assert_not_called()
        self.source.refresh_from_db()
        self.assertEqual((self.source.host, self.source.password), ("localhost", "test-password"))

    @patch("db_extraction.forms.test_connection", return_value={"server_version": "17", "schema_count": 1})
    def test_changed_connection_accepts_explicit_new_or_cleared_password(self, verify):
        data = dict(name="Example", host="other-host", port=5432, database_name="metadata",
                    username="metadata_reader", ssl_mode="prefer", connect_timeout=10,
                    enabled=True, included_schemas="")
        for password, clear, expected in [("replacement", False, "replacement"), ("", True, "")]:
            with self.subTest(clear=clear):
                form = DatabaseSourceForm(data={**data, "password": password, "clear_password": clear},
                                          instance=DatabaseSource.objects.get(pk=self.source.pk))
                self.assertTrue(form.is_valid(), form.errors.as_json())
                self.assertEqual(verify.call_args.args[0].password, expected)
                self.assertEqual(verify.call_args.args[0].host, "other-host")

    @patch("db_extraction.forms.test_connection", return_value={"server_version": "17", "schema_count": 1})
    def test_passwordless_profile_can_change_connection_without_reentering_password(self, verify):
        self.source.password = ""
        self.source.save()
        form = DatabaseSourceForm(data=dict(name="Example", host="other-host", port=5432,
            database_name="metadata", username="metadata_reader", password="", ssl_mode="prefer",
            connect_timeout=10, enabled=True, included_schemas=""), instance=self.source)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(verify.call_args.args[0].password, "")

    @patch("db_extraction.forms.test_connection", return_value={"server_version": "17", "schema_count": 1})
    def test_non_identity_edits_keep_password_but_removing_ca_requires_reentry(self, verify):
        data = dict(name="Renamed", host="localhost", port=5432, database_name="metadata",
                    username="metadata_reader", password="", ssl_mode="prefer", ssl_root_cert="",
                    connect_timeout=20, enabled=False, included_schemas="public")
        form = DatabaseSourceForm(data=data, instance=DatabaseSource.objects.get(pk=self.source.pk))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(verify.call_args.args[0].password, "test-password")
        verify.reset_mock()
        self.source.ssl_root_cert = "/tmp/original-ca.pem"
        self.source.save()
        form = DatabaseSourceForm(data=data, instance=DatabaseSource.objects.get(pk=self.source.pk))
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)
        verify.assert_not_called()

    def test_duplicate_constraint_names_are_scoped_to_each_table(self):
        run = ExtractionRun.objects.create(source=self.source, extractor_version="0.1.0")
        schema = DatabaseSchema.objects.create(run=run, name="public")
        first = DatabaseTable.objects.create(schema=schema, name="first")
        second = DatabaseTable.objects.create(schema=schema, name="second")
        values = dict(name="id_key", constraint_type="unique", definition="UNIQUE (id)")
        DatabaseConstraint.objects.create(table=first, **values)
        DatabaseConstraint.objects.create(table=second, **values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DatabaseConstraint.objects.create(table=first, **values)
        self.assertEqual(ExtractionRun.objects.get(pk=run.pk).extractor_version, "0.1.0")


class LegacyCredentialMigrationTests(TransactionTestCase):
    def test_existing_plaintext_is_encrypted_without_deleting_profiles(self):
        before = [("db_extraction", "0001_initial")]
        after = [("db_extraction", "0002_extractionrun_extractor_version_and_more")]
        executor = MigrationExecutor(connection)
        accounting_leaves = [
            node for node in executor.loader.graph.leaf_nodes()
            if node[0] in ("accounts_payable", "accounts_receivable")
        ]
        # These apps reference the database metadata tables. Remove their empty
        # test schema before reconstructing the historical db_extraction state.
        executor.migrate([("accounts_payable", None), ("accounts_receivable", None)])
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(accounting_leaves))
        # The security migration intentionally cannot be reversed into plaintext.
        # Remove only this test app's empty schema, then build its historical state.
        state = executor.loader.project_state(after)
        with connection.schema_editor() as editor:
            for name in ("ConstraintColumn", "DatabaseColumn", "DatabaseIndex", "DatabaseConstraint", "DatabaseTable", "DatabaseSchema", "ExtractionRun", "DatabaseSource"):
                editor.delete_model(cast(type[Model], state.apps.get_model("db_extraction", name)))
        executor.recorder.record_unapplied("db_extraction", after[0][1])
        executor.recorder.record_unapplied("db_extraction", before[0][1])
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        old_source = cast(type[DatabaseSource], executor.loader.project_state(before).apps.get_model("db_extraction", "DatabaseSource"))
        source = old_source.objects.create(name="Legacy", host="localhost", database_name="legacy", username="reader", password="legacy-password")
        old_source.objects.create(name="No password", host="localhost", database_name="other", username="reader", password="")
        with TemporaryDirectory() as directory:
            with self.settings(DB_EXTRACTION_CREDENTIAL_KEY_FILE=Path(directory) / "credentials.key"):
                # A missing key must fail transactionally, leaving legacy data intact.
                with self.assertRaises(ImproperlyConfigured):
                    MigrationExecutor(connection).migrate(after)
                self.assertEqual(old_source.objects.get(pk=source.pk).password, "legacy-password")
                call_command("init_db_credential_key", stdout=StringIO())
                MigrationExecutor(connection).migrate(after)
                self.assertEqual(DatabaseSource.objects.get(pk=source.pk).password, "legacy-password")
                self.assertEqual(DatabaseSource.objects.count(), 2)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT password FROM db_extraction_databasesource WHERE id = %s", [source.pk])
                    self.assertTrue(cursor.fetchone()[0].startswith(PASSWORD_PREFIX))
