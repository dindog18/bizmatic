"""Module reminder preferences and Encoder help are local, persistent and explicit."""
from unittest.mock import patch

from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from bizmatic_django.onboarding import checklist
from bizmatic_django.page_help import for_page
from document_extraction.models import WorkspaceSetupPreferences
from encoder.models import MCPConnection


@override_settings(ENCODER_LOCAL_ENABLED=True, ALLOWED_HOSTS=["localhost", "testserver"])
class WorkspaceSetupTests(TestCase):
    def setUp(self):
        self.environment = patch("bizmatic_django.onboarding.get_env", side_effect=lambda key, default="": default)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = Client(HTTP_HOST="localhost")

    def save(self, selected, revision=""):
        return self.client.post(reverse("setup_modules"), {"active_modules": selected, "revision": revision})

    def test_encoder_is_on_setup_and_get_does_not_create_preferences(self):
        response = self.client.get(reverse("setup"))
        self.assertContains(response, 'id="ENCODER"')
        self.assertContains(response, 'id="activate-ENCODER"')
        self.assertContains(response, "Encoding &amp; integrations")
        self.assertContains(response, reverse("ENCODER:connection_create"))
        self.assertFalse(WorkspaceSetupPreferences.objects.exists())
        self.assertEqual(self.client.get(reverse("setup_modules")).status_code, 405)

    def test_selection_persists_for_other_browsers_and_counts_only_selected_modules(self):
        self.assertEqual(self.save(["ENCODER"]).status_code, 302)
        preference = WorkspaceSetupPreferences.objects.get(pk=1)
        self.assertEqual(preference.active_modules, ["ENCODER"])
        response = Client(HTTP_HOST="localhost").get(reverse("setup"))
        encoder = next(group for group in response.context["setup_groups"] if group["key"] == "ENCODER")
        self.assertEqual(response.context["setup_missing"], encoder["missing"])
        self.assertIsNone(self.client.get("/accounts-payable/").context["setup_current"])
        self.assertNotContains(self.client.get("/accounts-receivable/"), "Accounts receivable needs setup.")
        response = self.client.get(reverse("ENCODER:dashboard"))
        self.assertEqual(response.context["setup_current"]["key"], "ENCODER")
        self.assertContains(response, "Encoder needs setup.")
        self.save([], preference.updated_at.isoformat())
        response = self.client.get(reverse("setup"))
        self.assertEqual(response.context["setup_missing"], 0)
        self.assertContains(response, "No active module needs setup.")
        self.assertIsNone(self.client.get(reverse("ENCODER:dashboard")).context["setup_current"])

    def test_stale_unknown_and_cross_site_changes_are_rejected(self):
        self.save(["ROUTER"])
        self.assertEqual(self.save(["UNSUPPORTED"]).status_code, 400)
        self.save(["ENCODER"], revision="stale")
        self.assertEqual(WorkspaceSetupPreferences.objects.get(pk=1).active_modules, ["ROUTER"])
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.assertEqual(client.post(reverse("setup_modules"), {}).status_code, 403)

    def test_checklist_never_decrypts_mcp_secrets_or_calls_mcp(self):
        MCPConnection.objects.create(name="Missing key fixture", command="unused", enabled=True)
        with patch("db_extraction.fields.EncryptedPasswordField.from_db_value", side_effect=AssertionError("Do not read secrets")), patch("encoder.services.mcp_client.connector") as connector:
            groups = checklist()
        self.assertIn("ENCODER", {group["key"] for group in groups})
        connector.assert_not_called()

    def test_encoder_get_pages_have_contextual_help_and_other_routes_keep_specific_guides(self):
        paths = {
            "/encoder/": "Encoder document queue", "/encoder/jobs/123/": "Encoder document workspace",
            "/encoder/connections/": "MCP connections", "/encoder/connections/new/": "Configure an MCP connection",
            "/encoder/connections/123/edit/": "Configure an MCP connection", "/encoder/connections/123/": "Review MCP tools",
            "/encoder/connections/123/mappings/tool/": "Reusable Encoder mapping", "/encoder/history/": "Encoder execution history",
            "/encoder/history/123/": "Encoder execution history", "/databases/123/runs/": "Database extraction history",
            "/databases/123/runs/456/": "Database extraction run", "/databases/123/runs/456/tables/789/": "Database table metadata",
            "/databases/123/delete/": "Delete a database connection", "/documents/123/delete/": "Delete a document or extraction",
        }
        for path, title in paths.items():
            request = RequestFactory().get(path)
            request.resolver_match = resolve(path)
            guide = for_page(request)
            self.assertEqual(guide["title"], title, path)
            self.assertTrue(guide["steps"], path)
        for path in ("/encoder/", "/encoder/connections/", "/encoder/connections/new/", "/encoder/history/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'id="page-tour-data"')
            self.assertEqual(response.context["page_guide"]["title"], paths[path])
