"""Approved MVP fixes, using only disposable accounting records and local stubs."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from .services import extraction, pages, records
from .services.catalog import model, party_key, revision
from .services.setup.configuration import clean_output


class ApprovedAccountingFixTests(TestCase):
    def setUp(self):
        self.rows = {}
        for mode in ("ap", "ar"):
            key = party_key(mode)
            account = model(mode, key).objects.create(**{key + "_code": "A1", key + "_name": "Test account"})
            order = model(mode, "purchase_order").objects.create(
                **{key: account}, po_reference_no="PO1", order_date="2026-10-25",
                currency="PHP", subtotal="100", total_amount="100",
            )
            invoice = model(mode, "sales_invoice").objects.create(
                **{key: account}, invoice_reference_no="INV1", invoice_date="2026-10-25",
                currency="PHP", subtotal="100", total_amount="100", invoice_status="posted",
            )
            receipt = model(mode, "delivery_receipt").objects.create(
                **{key: account}, dr_reference_no="DR1", delivery_date="2026-10-25",
            )
            order_line = model(mode, type(order).__name__ + "Line").objects.create(
                purchase_order=order, line_no=1, item_code="ITEM", unit_of_measure="pc",
                quantity_ordered="1", unit_price="100", line_total="100",
            )
            invoice_line = model(mode, type(invoice).__name__ + "Line").objects.create(
                invoice=invoice, line_no=1, item_code="ITEM", unit_of_measure="pc",
                quantity_invoiced="1", unit_price="100", line_total="100",
            )
            receipt_line = model(mode, type(receipt).__name__ + "Line").objects.create(
                delivery_receipt=receipt, line_no=1, item_code="ITEM", unit_of_measure="pc",
                quantity_stated="1", quantity_received="1", quantity_accepted="1",
            )
            case = records.save_case(mode, {
                "partyId": account.pk, "currency": "PHP", "date": "2026-10-25",
                "orderIds": [order.pk], "receiptIds": [receipt.pk], "invoiceIds": [invoice.pk],
            })
            payment = model(mode, "payment").objects.create(
                **{key: account, "amount_paid" if mode == "ap" else "amount_received": "100"},
                payment_reference_no="PAY1", currency="PHP", payment_status="cleared",
            )
            self.rows[mode] = dict(case=case, invoice=invoice, invoice_line=invoice_line,
                                   order_line=order_line, receipt_line=receipt_line, payment=payment)

    def match_payload(self, mode):
        rows = self.rows[mode]
        case = rows["case"]
        case.refresh_from_db()
        return {
            "revision": revision(case, [records.case_membership(case), records.matches(case)]),
            "matches": [{"invoiceLineId": rows["invoice_line"].pk, "orderLineId": rows["order_line"].pk,
                         "receiptLineId": rows["receipt_line"].pk, "quantity": "1"}],
        }

    def make_inconsistent_invoice(self, mode):
        rows = self.rows[mode]
        # Simulate saved source evidence, including records that predate this validation.
        type(rows["invoice"]).objects.filter(pk=rows["invoice"].pk).update(subtotal="150", total_amount="150")
        type(rows["invoice_line"]).objects.filter(pk=rows["invoice_line"].pk).update(line_total="150")

    def test_inconsistent_line_cannot_be_saved_as_matched(self):
        for mode in ("ap", "ar"):
            with self.subTest(mode=mode):
                self.make_inconsistent_invoice(mode)
                case = records.save_matches(mode, self.rows[mode]["case"].pk, self.match_payload(mode))
                self.assertEqual(case.reconciliation_status, "exception")
                self.assertEqual(case.line_matches.get().match_status, "exception")
                self.assertEqual(case.calculate_reconciliation()[1], Decimal("50.00"))
                self.rows[mode]["invoice_line"].refresh_from_db()
                self.assertEqual(self.rows[mode]["invoice_line"].line_total, Decimal("150"))

    def test_existing_matched_case_is_rechecked_without_overwriting_source_values(self):
        for mode in ("ap", "ar"):
            with self.subTest(mode=mode):
                case = records.save_matches(mode, self.rows[mode]["case"].pk, self.match_payload(mode))
                self.assertEqual(case.reconciliation_status, "matched")
                self.make_inconsistent_invoice(mode)
                state = pages.workspace_state(mode, "reconciliation")
                self.assertEqual(state["reconciliation"][0]["status"], "exception")
                self.assertEqual(state["reconciliation"][0]["discrepancy"], 50)
                self.assertEqual(state["reconciliation"][0]["matches"][0]["status"], "exception")
                self.assertTrue(state["invoices"][0]["lines"][0]["amountIssues"])
                case.refresh_from_db()
                self.assertEqual(case.reconciliation_status, "matched")  # Reading does not rewrite saved decisions.
                case.refresh_reconciliation_status()
                self.assertEqual(case.reconciliation_status, "exception")
                self.assertEqual(case.calculate_reconciliation()[1], Decimal("50.00"))

    def test_zero_quantity_invoice_needs_review_even_without_match_rows(self):
        for mode in ("ap", "ar"):
            with self.subTest(mode=mode):
                rows = self.rows[mode]
                type(rows["invoice_line"]).objects.filter(pk=rows["invoice_line"].pk).update(quantity_invoiced="0")
                rows["case"].refresh_reconciliation_status()
                self.assertEqual(rows["case"].reconciliation_status, "exception")
                self.assertEqual(rows["case"].calculate_reconciliation()[1], Decimal("100.00"))

    def test_workspace_amount_guidance_uses_the_configured_match_tolerance(self):
        for mode, app in (("ap", "accounts_payable"), ("ar", "accounts_receivable")):
            with self.subTest(mode=mode), self.settings(RECONCILIATION_PRICE_TOLERANCE="0.10"), patch(
                app + ".services.reconciliation.PRICE_TOLERANCE", Decimal("0.10")
            ):
                rows = self.rows[mode]
                type(rows["invoice"]).objects.filter(pk=rows["invoice"].pk).update(subtotal="100.05", total_amount="100.05")
                type(rows["invoice_line"]).objects.filter(pk=rows["invoice_line"].pk).update(line_total="100.05")
                case = records.save_matches(mode, rows["case"].pk, self.match_payload(mode))
                self.assertEqual(case.reconciliation_status, "matched")
                state = pages.workspace_state(mode, "reconciliation")
                self.assertEqual(state["invoices"][0]["lines"][0]["amountIssues"], [])
                self.assertEqual(state["reconciliation"][0]["matches"][0]["status"], "matched")

    def output(self, mode, source_type, target="sales_invoice"):
        config = model(mode, "ExtractionConfiguration")(
            target_entity=target, source_type=source_type, encoding_rules={}, relation_lookups={},
        )
        identity = ({"po_reference_no": "NEW-" + source_type, "order_date": "2026-10-25"}
                    if target == "purchase_order" else
                    {"invoice_reference_no": "NEW-" + source_type, "invoice_date": "2026-10-25"})
        quantity_field = "quantity_ordered" if target == "purchase_order" else "quantity_invoiced"
        result = {
            "record": {party_key(mode): "A1", **identity, "currency": "PHP", "subtotal": "150", "total_amount": "150"},
            "lines": [{"line_no": 1, quantity_field: "1", "unit_price": "100", "line_total": "150"}],
            "issues": [],
        }
        return config, result

    def test_document_and_database_setup_and_final_save_reject_bad_line_math(self):
        for mode in ("ap", "ar"):
            for source_type in ("document", "database"):
                for target in ("purchase_order", "sales_invoice"):
                    with self.subTest(mode=mode, source=source_type, target=target):
                        config, result = self.output(mode, source_type, target)
                        self.assertTrue(clean_output(mode, config, result))
                        before = model(mode, target).objects.count()
                        with self.assertRaises(ValidationError):
                            extraction.save_result(mode, config, result)
                        self.assertEqual(model(mode, target).objects.count(), before)

    def test_large_quantity_and_price_need_review_instead_of_crashing_decimal_math(self):
        for mode in ("ap", "ar"):
            with self.subTest(mode=mode):
                config, result = self.output(mode, "document")
                result["lines"][0].update(quantity_invoiced="99999999999999.0000", unit_price="99999999999999.0000")
                self.assertTrue(clean_output(mode, config, result))
                with self.assertRaises(ValidationError):
                    extraction.save_result(mode, config, result)
                rows = self.rows[mode]
                type(rows["invoice_line"]).objects.filter(pk=rows["invoice_line"].pk).update(
                    quantity_invoiced="99999999999999.0000", unit_price="99999999999999.0000")
                with self.assertRaises(ValidationError):
                    rows["case"].refresh_reconciliation_status()
                rows["case"].refresh_from_db()
                self.assertEqual(rows["case"].total_discrepancy_amount, Decimal("100.00"))
                state = pages.workspace_state(mode, "reconciliation")
                self.assertEqual(state["reconciliation"][0]["status"], "exception")
                self.assertIsNone(state["reconciliation"][0]["discrepancy"])
                self.assertTrue(state["reconciliation"][0]["calculationIssue"])

    def test_rounding_discount_tax_and_header_charges_remain_valid(self):
        for mode in ("ap", "ar"):
            for source_type in ("document", "database"):
                with self.subTest(mode=mode, source=source_type):
                    config, result = self.output(mode, source_type)
                    result["record"].update(subtotal="1.01", discount_amount="0.10", tax_amount="0.20", total_amount="1.11")
                    result["lines"][0].update(quantity_invoiced="3", unit_price="0.3350",
                                              discount_amount="0.10", tax_amount="0.20", line_total="1.11")
                    if mode == "ap":
                        result["record"].update(other_charges="5", total_amount="6.11")
                    self.assertEqual(clean_output(mode, config, result), [])
                    saved = extraction.save_result(mode, config, result)
                    self.assertEqual(saved.lines.get().line_total, Decimal("1.11"))

    def test_invalid_match_rows_return_400_and_preserve_matches(self):
        for mode, slug in (("ap", "accounts-payable"), ("ar", "accounts-receivable")):
            case = records.save_matches(mode, self.rows[mode]["case"].pk, self.match_payload(mode))
            original = records.matches(case)
            for row in (None, "invalid", [], 1, True):
                with self.subTest(mode=mode, row=row):
                    payload = self.match_payload(mode)
                    payload["matches"].append(row)
                    response = self.client.post(f"/{slug}/api/matches/{case.pk}/", payload, content_type="application/json")
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn("object", response.json()["message"])
                    self.assertEqual(records.matches(case), original)

    def test_invalid_allocation_rows_return_400_and_preserve_allocations(self):
        for mode, slug in (("ap", "accounts-payable"), ("ar", "accounts-receivable")):
            rows = self.rows[mode]
            payment = rows["payment"]
            payment.refresh_from_db()
            records.save_allocations(mode, payment.pk, {
                "revision": revision(payment, records.allocations(payment)),
                "allocations": [{"invoiceId": rows["invoice"].pk, "cash": "40"}],
            })
            original = records.allocations(payment)
            for row in (None, "invalid", [], 1, True):
                with self.subTest(mode=mode, row=row):
                    payment.refresh_from_db()
                    payload = {"revision": revision(payment, original), "allocations": [row]}
                    response = self.client.post(f"/{slug}/api/allocations/{payment.pk}/", payload, content_type="application/json")
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn("object", response.json()["message"])
                    self.assertEqual(records.allocations(payment), original)
