"""Preserve accounting data when removing the approval workflow."""

from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SimplificationMigrationTests(TransactionTestCase):
    def test_notes_charges_and_statuses_survive_simplification(self):
        executor = MigrationExecutor(connection)
        after = [
            node for node in executor.loader.graph.leaf_nodes()
            if node[0] in ("accounts_payable", "accounts_receivable")
        ]
        before = [
            ("accounts_payable", "0007_companypayment_ap_payment_source_record_uq_and_more"),
            ("accounts_receivable", "0006_companydeliveryreceipt_ar_dr_source_record_uq_and_more"),
        ]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(after))
        executor.migrate(before)
        historical = executor.loader.project_state(before).apps
        supplier = historical.get_model("accounts_payable", "Supplier").objects.create(
            supplier_code="LEGACY-S", supplier_name="Supplier",
        )
        order = historical.get_model("accounts_payable", "CompanyPurchaseOrder").objects.create(
            supplier=supplier, po_reference_no="LEGACY-PO", order_date=date(2026, 1, 1),
            currency="PHP", status="approved", approved_other_charges=Decimal("7.50"),
        )
        invoice = historical.get_model("accounts_payable", "SupplierSalesInvoice").objects.create(
            supplier=supplier, invoice_reference_no="LEGACY-INV", currency="PHP",
            invoice_status="approved", review_notes="Invoice discrepancy explanation",
        )
        case = historical.get_model("accounts_payable", "Transaction").objects.create(
            supplier=supplier, review_notes="Case notes", payment_approval_status="approved",
        )
        customer = historical.get_model("accounts_receivable", "Customer").objects.create(
            customer_code="LEGACY-C", customer_name="Customer",
        )
        customer_order = historical.get_model("accounts_receivable", "CustomerPurchaseOrder").objects.create(
            customer=customer, po_reference_no="LEGACY-CPO", order_date=date(2026, 1, 1),
            currency="PHP", status="approved",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        current = executor.loader.project_state(after).apps
        migrated_order = current.get_model("accounts_payable", "CompanyPurchaseOrder").objects.get(pk=order.pk)
        migrated_invoice = current.get_model("accounts_payable", "SupplierSalesInvoice").objects.get(pk=invoice.pk)
        migrated_case = current.get_model("accounts_payable", "Transaction").objects.get(pk=case.pk)
        self.assertEqual(migrated_order.status, "open")
        self.assertEqual(migrated_order.other_charges, Decimal("7.50"))
        self.assertEqual(migrated_invoice.invoice_status, "posted")
        self.assertEqual(migrated_invoice.notes, "Invoice discrepancy explanation")
        self.assertEqual(migrated_case.notes, "Case notes")
        self.assertEqual(
            current.get_model("accounts_receivable", "CustomerPurchaseOrder").objects.get(pk=customer_order.pk).status,
            "open",
        )
