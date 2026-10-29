"""Server-backed frontend configuration and persisted bootstrap records."""

import json

from django.test import TestCase
from django.urls import reverse

from .models import RoutingDestination, RoutingRule


class RoutingFrontendTests(TestCase):
    def test_tabs_render_database_bootstrap_without_preview_fixtures(self):
        for name in ("queue", "destinations", "destination_create", "rules", "rule_create", "logs"):
            response = self.client.get(reverse(f"ROUTER:{name}"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'id="router-state"')
            self.assertNotContains(response, "router/demo-data.js")
            self.assertNotContains(response, "router/requests.js")
            self.assertNotContains(response, "Reset preview")
        self.assertEqual(self.client.get(reverse("ROUTER:destination_edit", args=[9999])).status_code, 404)

    def test_configuration_save_validates_installed_model_and_duplicates(self):
        url = reverse("ROUTER:configuration_save", args=["destinations"])
        data = {"name": "Supplier invoices", "module_name": "accounts_payable", "target_model": "SupplierSalesInvoice", "description": "Supplier invoice documents", "is_active": True}
        response = self.client.post(url, data, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        destination = RoutingDestination.objects.get()
        self.assertEqual(self.client.post(url, data, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, {**data, "target_model": "NoSuchModel"}, content_type="application/json").status_code, 400)
        response = self.client.post(reverse("ROUTER:configuration_save", args=["rules"]), {
            "name": "Supplier invoices", "destination_id": destination.pk, "instructions": "Issued by a supplier to our company", "is_active": True,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(RoutingRule.objects.get().destination, destination)
        state = self.client.get(reverse("ROUTER:destinations")).context["router_state"]
        self.assertEqual(state["destinations"][0]["id"], destination.pk)

    def test_configuration_revision_prevents_lost_updates(self):
        destination = RoutingDestination.objects.create(name="Payments", module_name="accounts_payable", target_model="CompanyPayment")
        url = reverse("ROUTER:configuration_toggle", args=["destinations", destination.pk])
        payload = {"is_active": False, "revision": destination.updated_at.isoformat()}
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 200)
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 409)
        destination.refresh_from_db()
        self.assertFalse(destination.is_active)

    def test_configuration_endpoints_reject_get_and_invalid_shapes(self):
        url = reverse("ROUTER:configuration_save", args=["destinations"])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, json.dumps([]), content_type="application/json").status_code, 400)

    def test_destination_catalog_matches_accounting_extraction_targets(self):
        from accounts_receivable.ui import configuration_catalog
        from .services.catalog import destination_catalog

        catalog = destination_catalog()
        self.assertEqual([module["value"] for module in catalog], ["accounts_payable", "accounts_receivable"])
        for module, mode in zip(catalog, ("ap", "ar")):
            self.assertEqual([target["value"] for target in module["targets"]],
                             [target["model"] for target in configuration_catalog(mode)])
        response = self.client.get(reverse("ROUTER:destination_create"))
        self.assertEqual(response.context["router_config"]["destinationCatalog"], catalog)

    def test_destination_choices_reject_cross_module_and_internal_models(self):
        url = reverse("ROUTER:configuration_save", args=["destinations"])
        for target in ("CompanySalesInvoice", "CompanyPurchaseOrderLine", "Transaction", "DocumentMatch", "PaymentAllocation", "ExtractionConfiguration", "LLMExtractionLog"):
            response = self.client.post(url, {"name": "Invalid destination", "module_name": "accounts_payable", "target_model": target, "is_active": True}, content_type="application/json")
            self.assertEqual(response.status_code, 400, target)
        response = self.client.post(url, {"name": "Invalid module", "module_name": "document_extraction", "target_model": "Document", "is_active": True}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(RoutingDestination.objects.exists())

    def test_all_ten_accounting_target_choices_can_be_saved(self):
        from .services.catalog import destination_catalog

        url = reverse("ROUTER:configuration_save", args=["destinations"])
        for module in destination_catalog():
            for target in module["targets"]:
                response = self.client.post(url, {"name": target["label"], "module_name": module["value"], "target_model": target["value"], "is_active": True}, content_type="application/json")
                self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(RoutingDestination.objects.count(), 10)

    def test_saved_legacy_destination_can_keep_its_identity(self):
        legacy = RoutingDestination.objects.create(name="Legacy source", module_name="document_extraction", target_model="Document")
        response = self.client.post(reverse("ROUTER:configuration_edit", args=["destinations", legacy.pk]), {
            "name": "Legacy source renamed", "module_name": legacy.module_name, "target_model": legacy.target_model,
            "description": "Keep the saved identity", "is_active": True, "revision": legacy.updated_at.isoformat(),
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        legacy.refresh_from_db()
        self.assertEqual(legacy.target_model, "Document")
