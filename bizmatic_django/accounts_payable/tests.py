from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import (
    CompanyPayment, CompanyPurchaseOrder, CompanyPurchaseOrderLine,
    DocumentMatch, PaymentAllocation, Supplier, SupplierDeliveryReceipt,
    SupplierDeliveryReceiptLine, SupplierSalesInvoice, SupplierSalesInvoiceLine,
    Transaction,
)


class ThreeWayMatchTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(supplier_code="S1", supplier_name="Supplier")
        self.order = CompanyPurchaseOrder.objects.create(
            supplier=self.supplier, po_reference_no="PO1", order_date=date.today(),
            currency="PHP", subtotal=Decimal("100.00"), total_amount=Decimal("100.00"),
        )
        self.receipt = SupplierDeliveryReceipt.objects.create(
            supplier=self.supplier, dr_reference_no="DR1", delivery_date=date.today(),
            receipt_status="accepted",
        )
        self.invoice = SupplierSalesInvoice.objects.create(
            supplier=self.supplier, invoice_reference_no="INV1", invoice_date=date.today(),
            currency="PHP", subtotal=Decimal("60.00"), total_amount=Decimal("60.00"),
        )
        self.order_line = CompanyPurchaseOrderLine.objects.create(
            purchase_order=self.order, line_no=1, item_code="A", unit_of_measure="ea",
            quantity_ordered=Decimal("10"), unit_price=Decimal("10"), line_total=Decimal("100"),
        )
        self.receipt_line = SupplierDeliveryReceiptLine.objects.create(
            delivery_receipt=self.receipt, line_no=1, item_code="A", unit_of_measure="ea",
            quantity_stated=Decimal("6"), quantity_received=Decimal("6"), quantity_accepted=Decimal("6"),
        )
        self.invoice_line = SupplierSalesInvoiceLine.objects.create(
            invoice=self.invoice, line_no=1, item_code="A", unit_of_measure="ea",
            quantity_invoiced=Decimal("6"), unit_price=Decimal("10"), line_total=Decimal("60"),
        )
        self.case = Transaction.objects.create(supplier=self.supplier, transaction_date=date.today(), currency="PHP")
        self.case.purchase_orders.add(self.order)
        self.case.delivery_receipts.add(self.receipt)
        self.case.sales_invoices.add(self.invoice)

    def test_match_uses_accepted_quantities_and_prevents_reuse(self):
        DocumentMatch.objects.create(
            transaction=self.case, purchase_order_line=self.order_line,
            delivery_receipt_line=self.receipt_line, invoice_line=self.invoice_line,
            matched_quantity=Decimal("6"), match_status="matched",
        )
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status, "matched")
        with self.assertRaises(ValidationError):
            DocumentMatch.objects.create(
                transaction=self.case, purchase_order_line=self.order_line,
                delivery_receipt_line=self.receipt_line, invoice_line=self.invoice_line,
                matched_quantity=Decimal("1"), match_status="matched",
            )
        self.receipt.dr_reference_no = None
        self.receipt.save()
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status, "exception")
        with self.assertRaises(ValidationError):
            DocumentMatch.objects.get().full_clean()

    def test_payment_allocation_and_reversal(self):
        payment = CompanyPayment.objects.create(
            supplier=self.supplier, payment_reference_no="PAY1", currency="PHP",
            amount_paid=Decimal("50"), withholding_tax_amount=Decimal("5"),
            discount_taken=Decimal("5"),
        )
        PaymentAllocation.objects.create(
            payment=payment, invoice=self.invoice, cash_amount=Decimal("50"),
            withholding_tax_amount=Decimal("5"), discount_amount=Decimal("5"),
        )
        payment.payment_status = "cleared"
        payment.save()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "paid")
        self.assertEqual(self.invoice.outstanding_balance, Decimal("0"))
        self.assertEqual(payment.unallocated_amount, Decimal("0"))
        payment.payment_status = "reversed"
        payment.save()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "unpaid")
        self.assertEqual(self.invoice.outstanding_balance, Decimal("60"))
        replacement = CompanyPayment.objects.create(
            supplier=self.supplier, payment_reference_no="PAY2", currency="PHP",
            amount_paid=Decimal("60"),
        )
        PaymentAllocation.objects.create(payment=replacement, invoice=self.invoice, cash_amount=Decimal("60"))
        self.assertEqual(replacement.unallocated_amount, Decimal("0"))

    def test_invoice_charges_are_compared_with_order_charges(self):
        self.invoice.other_charges = Decimal("5")
        self.invoice.total_amount = Decimal("65")
        self.invoice.save()
        DocumentMatch.objects.create(
            transaction=self.case, purchase_order_line=self.order_line,
            delivery_receipt_line=self.receipt_line, invoice_line=self.invoice_line,
            matched_quantity=Decimal("6"), match_status="matched",
        )
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status, "exception")
        self.order.other_charges = Decimal("5")
        self.order.total_amount = Decimal("105")
        self.order.save()
        self.case.refresh_reconciliation_status()
        self.assertEqual(self.case.reconciliation_status, "matched")

    def test_removing_invoice_reopens_case(self):
        DocumentMatch.objects.create(
            transaction=self.case, purchase_order_line=self.order_line,
            delivery_receipt_line=self.receipt_line, invoice_line=self.invoice_line,
            matched_quantity=Decimal("6"), match_status="matched",
        )
        self.case.sales_invoices.remove(self.invoice)
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status, "exception")
