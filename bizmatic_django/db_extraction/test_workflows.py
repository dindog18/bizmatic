"""HTTP workflow, anonymous access, and atomic snapshot regression checks."""

from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from .models import DatabaseColumn, DatabaseConstraint, DatabaseSource, DatabaseTable, ExtractionRun
from .services.extraction import refresh_source
from .services.postgres import CatalogSnapshot, InspectionError


def catalog():
    return CatalogSnapshot(
        database_name="example", server_version="17",
        schemas=[dict(oid=1, name="public", owner="reader", comment="Schema")],
        tables=[dict(oid=2, schema_oid=1, name="orders", relation_kind="r", owner="reader", comment="Orders",
                     view_definition="", partition_definition="", row_security_enabled=False)],
        columns=[dict(table_oid=2, name="company_id", ordinal_position=1, formatted_type="integer", nullable=False),
                 dict(table_oid=2, name="customer_id", ordinal_position=2, formatted_type="integer", nullable=False)],
        constraints=[dict(oid=3, table_oid=2, name="customer_fk", constraint_type="f", definition="FOREIGN KEY (company_id, customer_id) REFERENCES customers(company_id, id)",
                          column_positions=[1, 2], referenced_columns=["company_id", "id"], referenced_schema="external",
                          referenced_table="customers", update_code="a", delete_code="c", match_code="s",
                          is_deferrable=True, initially_deferred=False, is_validated=True)],
        indexes=[dict(table_oid=2, name="customer_idx", definition="CREATE INDEX customer_idx ON orders (customer_id)",
                      access_method="btree", is_unique=False, is_primary=False, is_valid=True, predicate="", comment="")],
    )


class WorkspaceTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(DB_EXTRACTION_CREDENTIAL_KEY_FILE=Path(directory.name) / "key")
        override.enable()
        self.addCleanup(override.disable)
        call_command("init_db_credential_key", stdout=StringIO())
        self.source = DatabaseSource.objects.create(name="Existing", host="localhost", database_name="example", username="reader", password="saved-secret")
        self.form_data = dict(name="New", host="localhost", port=5432, database_name="example", username="reader",
                              password="new-secret", ssl_mode="prefer", connect_timeout=10, included_schemas="public, public", enabled="on")
        self.verification = dict(database_name="example", server_version="17", schema_count=1)

    @staticmethod
    def path(name, **kwargs):
        return reverse(f"DB_EXTRACTION:{name}", kwargs=kwargs)

    def test_workspace_pages_open_without_an_account(self):
        for name, kwargs in [("source_list", {}), ("source_create", {}), ("source_detail", {"source_id": self.source.pk}),
                             ("source_edit", {"source_id": self.source.pk}), ("run_list", {"source_id": self.source.pk}),
                             ("source_delete", {"source_id": self.source.pk})]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(self.path(name, **kwargs)).status_code, 200)

    @patch("db_extraction.views.test_connection")
    @patch("db_extraction.services.extraction.inspect_database")
    def test_saved_connection_test_and_refresh_work_without_login(self, inspect, verify):
        inspect.return_value = catalog()
        verify.return_value = self.verification
        response = self.client.post(self.path("source_test", source_id=self.source.pk))
        self.assertRedirects(response, self.path("source_detail", source_id=self.source.pk))
        verify.assert_called_once()
        response = self.client.post(self.path("source_refresh", source_id=self.source.pk))
        run = ExtractionRun.objects.get(source=self.source)
        self.assertEqual(run.status, "completed")
        self.assertRedirects(response, self.path("run_detail", source_id=self.source.pk, run_id=run.pk))

    @patch("db_extraction.forms.test_connection")
    def test_connection_test_does_not_save_and_save_retests_exact_settings(self, verify):
        verify.return_value = self.verification
        url = self.path("source_create")
        response = self.client.post(url, {**self.form_data, "intent": "test"})
        self.assertContains(response, "Connection verified")
        self.assertEqual(DatabaseSource.objects.count(), 1)
        self.assertNotContains(response, 'value="new-secret"')
        self.assertEqual(verify.call_args.args[0].included_schemas, ["public"])
        response = self.client.post(url, {**self.form_data, "host": "changed-host", "intent": "save"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DatabaseSource.objects.get(name="New").host, "changed-host")
        self.assertEqual(verify.call_count, 2)

    @patch("db_extraction.forms.test_connection", side_effect=InspectionError("Connection failed."))
    def test_invalid_connection_is_not_saved(self, _verify):
        response = self.client.post(self.path("source_create"), self.form_data)
        self.assertContains(response, "Connection failed.")
        self.assertEqual(DatabaseSource.objects.count(), 1)

    @patch("db_extraction.forms.test_connection")
    def test_ajax_connection_test_never_echoes_password_or_saves(self, verify):
        verify.return_value = self.verification
        response = self.client.post(self.path("source_create"), {**self.form_data, "intent": "test"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Connection verified", response.json()["message"])
        self.assertNotContains(response, "new-secret")
        self.assertEqual(DatabaseSource.objects.count(), 1)

    @patch("db_extraction.forms.test_connection")
    def test_edit_preserves_password_and_handles_invalid_schema_input(self, verify):
        verify.return_value = self.verification
        url = self.path("source_edit", source_id=self.source.pk)
        response = self.client.post(url, {**self.form_data, "name": "Existing", "password": "", "included_schemas": " public, reporting "})
        self.assertEqual(response.status_code, 302)
        self.source.refresh_from_db()
        self.assertEqual(self.source.password, "saved-secret")
        self.assertEqual(self.source.included_schemas, ["public", "reporting"])
        response = self.client.get(url)
        self.assertNotContains(response, "saved-secret")

    @patch("db_extraction.services.extraction.inspect_database")
    def test_refresh_saves_ordered_composite_keys_and_browseable_metadata(self, inspect):
        inspect.return_value = catalog()
        run = refresh_source(self.source.pk)
        self.assertEqual(run.status, "completed")
        self.assertEqual(list(DatabaseConstraint.objects.get().columns.values_list("column__name", "referenced_column_name")),
                         [("company_id", "company_id"), ("customer_id", "id")])
        for name, kwargs in [("source_list", {}), ("source_detail", {"source_id": self.source.pk}),
                             ("run_list", {"source_id": self.source.pk}), ("run_detail", {"source_id": self.source.pk, "run_id": run.pk}),
                             ("table_detail", {"source_id": self.source.pk, "run_id": run.pk, "table_id": DatabaseTable.objects.get().pk})]:
            self.assertEqual(self.client.get(self.path(name, **kwargs)).status_code, 200)
        response = self.client.get(self.path("source_detail", source_id=self.source.pk), {"q": "missing"})
        self.assertContains(response, "No matching tables")
        self.assertNotContains(response, "saved-secret")

    @patch("db_extraction.services.extraction.inspect_database")
    def test_failed_refresh_rolls_back_partial_metadata_and_keeps_previous_snapshot(self, inspect):
        inspect.return_value = catalog()
        previous = refresh_source(self.source.pk)
        broken = deepcopy(catalog())
        broken.columns.append(broken.columns[0])
        inspect.return_value = broken
        failed = refresh_source(self.source.pk)
        self.assertEqual(failed.status, "failed")
        self.assertFalse(failed.schemas.exists())
        self.assertEqual(DatabaseColumn.objects.count(), 2)
        self.assertEqual(self.source.extraction_runs.filter(status="completed").first(), previous)
        response = self.client.get(self.path("source_detail", source_id=self.source.pk))
        self.assertContains(response, "last successful snapshot")

    @patch("db_extraction.services.extraction.inspect_database")
    def test_concurrent_and_disabled_refresh_are_rejected_and_cross_source_urls_are_404(self, inspect):
        inspect.return_value = catalog()
        run = refresh_source(self.source.pk)
        other = DatabaseSource.objects.create(name="Other", host="localhost", database_name="other", username="reader")
        url = self.path("run_detail", source_id=other.pk, run_id=run.pk)
        self.assertEqual(self.client.get(url).status_code, 404)
        ExtractionRun.objects.create(source=self.source, status="running")
        with self.assertRaises(InspectionError):
            refresh_source(self.source.pk)
        self.source.enabled = False
        self.source.save()
        with self.assertRaises(InspectionError):
            refresh_source(self.source.pk)

    @patch("db_extraction.services.extraction.inspect_database")
    def test_confirmed_delete_cascades_locally_and_never_connects_to_source(self, inspect):
        inspect.return_value = catalog()
        refresh_source(self.source.pk)
        inspect.reset_mock()
        url = self.path("source_delete", source_id=self.source.pk)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {})
        self.assertTrue(DatabaseSource.objects.filter(pk=self.source.pk).exists())
        response = self.client.post(url, {"confirm": "yes"})
        self.assertRedirects(response, self.path("source_list"))
        self.assertEqual(ExtractionRun.objects.count(), 0)
        self.assertEqual(DatabaseColumn.objects.count(), 0)
        self.assertFalse(DatabaseSource.objects.exists())
        inspect.assert_not_called()

    def test_every_write_requires_csrf_and_safe_methods_do_not_trigger_refresh(self):
        csrf = Client(enforce_csrf_checks=True)
        for name in ("source_test", "source_refresh"):
            url = self.path(name, source_id=self.source.pk)
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(csrf.post(url).status_code, 403)
        self.assertEqual(csrf.post(self.path("source_create"), self.form_data).status_code, 403)
        self.assertEqual(csrf.post(self.path("source_edit", source_id=self.source.pk), self.form_data).status_code, 403)
        self.assertEqual(csrf.post(self.path("source_delete", source_id=self.source.pk), {"confirm": "yes"}).status_code, 403)
