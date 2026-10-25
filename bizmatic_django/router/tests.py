from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from document_extraction.models import Document

from .models import DocumentRoute, LLMRoutingLog, ReviewStatus, RoutingDestination, RoutingRule


class RoutingModelTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(
            file_name="invoice.pdf", document_type="pdf", storage_path="/tmp/invoice.pdf",
        )
        self.destination = RoutingDestination.objects.create(
            name="Supplier invoice", module_name="accounts_payable",
            target_model="SupplierSalesInvoice",
        )
        self.log = LLMRoutingLog.objects.create(source_document=self.document, status="completed")

    def test_document_can_have_multiple_destinations_with_independent_reviews(self):
        approved = DocumentRoute.objects.create(
            routing_log=self.log, destination=self.destination,
            review_status=ReviewStatus.APPROVED,
        )
        # A future module needs configuration rows, without new router fields.
        future = RoutingDestination.objects.create(
            name="Inventory receipt", module_name="inventory", target_model="GoodsReceipt",
        )
        pending = DocumentRoute.objects.create(routing_log=self.log, destination=future)

        self.assertEqual(self.log.routes.count(), 2)
        self.assertEqual(approved.review_status, ReviewStatus.APPROVED)
        self.assertEqual(pending.review_status, ReviewStatus.PENDING)
        self.assertEqual(pending.routing_log.source_document, self.document)

    def test_duplicate_destination_is_rejected_but_rerun_is_allowed(self):
        DocumentRoute.objects.create(routing_log=self.log, destination=self.destination)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentRoute.objects.create(routing_log=self.log, destination=self.destination)

        rerun = LLMRoutingLog.objects.create(source_document=self.document, status="completed")
        DocumentRoute.objects.create(routing_log=rerun, destination=self.destination)
        self.assertEqual(self.document.routing_logs.count(), 2)

    def test_configuration_changes_preserve_saved_run_inputs(self):
        rule = RoutingRule.objects.create(
            name="Supplier invoices", destination=self.destination,
            document_type="sales_invoice", instructions="Match invoices issued by suppliers.",
        )
        self.log.input_text = "Invoice INV-001"
        self.log.prompt_text = "Select every matching destination."
        self.log.rules_snapshot = [{
            "rule_no": rule.pk, "instructions": rule.instructions,
            "module_name": self.destination.module_name,
            "target_model": self.destination.target_model,
        }]
        self.log.save()

        rule.instructions = "New instructions."
        rule.save()
        self.destination.target_model = "CompanyPayment"
        self.destination.save()
        self.log.refresh_from_db()
        self.assertEqual(self.log.input_text, "Invoice INV-001")
        self.assertEqual(self.log.rules_snapshot[0]["instructions"], "Match invoices issued by suppliers.")
        self.assertEqual(self.log.rules_snapshot[0]["target_model"], "SupplierSalesInvoice")

    def test_confidence_range_is_enforced_for_database_writes(self):
        for confidence in (Decimal("-0.0001"), Decimal("1.0001")):
            with self.subTest(confidence=confidence):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    DocumentRoute.objects.create(
                        routing_log=self.log, destination=self.destination, confidence=confidence,
                    )
        route = DocumentRoute.objects.create(
            routing_log=self.log, destination=self.destination, confidence=Decimal("1"),
        )
        self.assertEqual(route.review_status, ReviewStatus.PENDING)
