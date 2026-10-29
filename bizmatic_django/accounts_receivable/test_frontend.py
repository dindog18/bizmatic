"""Production workspace pages use saved records and keep AP/AR routes separate."""

from django.test import TestCase
from django.urls import NoReverseMatch, resolve, reverse


class AccountingFrontendTests(TestCase):
    namespaces = ("ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE")
    resources = ("party", "purchase_order", "delivery_receipt", "invoice", "payment", "reconciliation")

    def test_workspace_lists_and_record_first_setup_render(self):
        for namespace in self.namespaces:
            for name in ('overview', 'aging', 'party_list', 'invoice_list', 'configuration_list', 'configuration_create'):
                with self.subTest(namespace=namespace, route=name):
                    response = self.client.get(reverse(f'{namespace}:{name}'))
                    self.assertEqual(response.status_code, 200)
                    self.assertTemplateUsed(response, 'accounting/setup.html' if name == 'configuration_create' else 'accounting/workspace.html')
                    self.assertContains(response, 'id="finance-config"')
                    if name == 'configuration_create':
                        self.assertContains(response, 'accounting/setup/workspace.js')
                        self.assertNotContains(response, 'accounting/configuration.js')
            self.assertEqual(self.client.get(reverse(f'{namespace}:invoice_detail', args=[999])).status_code, 404)

    def test_accounting_routes_never_accept_mutations(self):
        for namespace in self.namespaces:
            for name, args in (("overview", []), ("invoice_list", []), ("invoice_detail", [1]), ("party_create", []), ("reconciliation_edit", [1]), ("payment_allocate", [1]), ("reconciliation_match", [1])):
                endpoint = reverse(f"{namespace}:{name}", args=args)
                for method in ("post", "put", "patch", "delete"):
                    with self.subTest(namespace=namespace, route=name, method=method):
                        response = getattr(self.client, method)(endpoint)
                        self.assertEqual(response.status_code, 405)
                        self.assertEqual(response.headers["Allow"], "GET, HEAD")

    def test_workspace_config_and_source_destinations_are_isolated(self):
        for namespace, mode, slug in ((self.namespaces[0], "ar", "customers"), (self.namespaces[1], "ap", "suppliers")):
            with self.subTest(mode=mode):
                response = self.client.get(reverse(f"{namespace}:invoice_list"))
                config = response.context["finance_config"]
                self.assertEqual(config["mode"], mode)
                self.assertIsNone(config["recordId"])
                self.assertEqual(config["screen"], "list")
                self.assertFalse(config["canEncode"])
                self.assertTrue(config["routes"]["parties"].endswith(f"/{slug}/"))
                for route in config["routes"].values():
                    self.assertEqual(resolve(route).namespace, namespace)
                self.assertEqual(config["sources"]["documents"], reverse("DOC_EXTRACTION:document_list"))
                self.assertEqual(config["sources"]["databases"], reverse("DB_EXTRACTION:source_list"))
                self.assertContains(response, reverse(f"{self.namespaces[0]}:overview"))
                self.assertContains(response, reverse(f"{self.namespaces[1]}:overview"))

    def test_extracted_records_have_no_encoding_routes(self):
        for namespace in self.namespaces:
            for name in ("purchase_order", "delivery_receipt", "invoice", "payment"):
                endpoint = reverse(f"{namespace}:{name}_list")
                for path in (endpoint + "new/", endpoint + "1/edit/"):
                    with self.subTest(namespace=namespace, path=path):
                        self.assertEqual(self.client.get(path).status_code, 404)
                for action in ("create", "edit"):
                    with self.subTest(namespace=namespace, name=name, action=action):
                        with self.assertRaises(NoReverseMatch):
                            reverse(f"{namespace}:{name}_{action}", args=[1] if action == "edit" else [])

    def test_accounts_and_reconciliation_remain_editable(self):
        for namespace in self.namespaces:
            for name in ("party", "reconciliation"):
                response = self.client.get(reverse(f"{namespace}:{name}_create"))
                self.assertTrue(response.context["finance_config"]["canEncode"])

    def test_head_and_unknown_route(self):
        self.assertEqual(self.client.head(reverse("ACCOUNTS_RECEIVABLE:overview")).status_code, 200)
        self.assertEqual(self.client.get("/accounts-payable/unknown-resource/").status_code, 404)
