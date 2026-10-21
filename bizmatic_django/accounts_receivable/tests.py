from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from db_extraction.models import DatabaseSchema, DatabaseSource, DatabaseTable, ExtractionRun

from .models import (
    CompanyDeliveryReceipt, CompanyDeliveryReceiptLine, CompanySalesInvoice,
    CompanySalesInvoiceLine, Customer, CustomerPayment, CustomerPurchaseOrder,
    CustomerPurchaseOrderLine, DocumentMatch, PaymentAllocation, Transaction,
)


class ReceivablesMatchTests(TestCase):
    def test_partial_payment_and_price_exception(self):
        customer = Customer.objects.create(customer_code="C1", customer_name="Customer")
        order = CustomerPurchaseOrder.objects.create(
            customer=customer, po_reference_no="PO1", order_date=date.today(),
            currency="PHP", subtotal=Decimal("100"), total_amount=Decimal("100"),
        )
        receipt = CompanyDeliveryReceipt.objects.create(
            customer=customer, dr_reference_no="DR1", delivery_date=date.today(),
            delivery_status="delivered",
        )
        invoice = CompanySalesInvoice.objects.create(
            customer=customer, invoice_reference_no="INV1", invoice_date=date.today(),
            currency="PHP", subtotal=Decimal("100"), total_amount=Decimal("100"),
        )
        order_line = CustomerPurchaseOrderLine.objects.create(
            purchase_order=order, line_no=1, item_code="A", quantity_ordered=Decimal("10"),
            unit_price=Decimal("10"), line_total=Decimal("100"),
        )
        receipt_line = CompanyDeliveryReceiptLine.objects.create(
            delivery_receipt=receipt, line_no=1, item_code="A", quantity_stated=Decimal("10"),
            quantity_received=Decimal("10"), quantity_accepted=Decimal("10"),
        )
        invoice_line = CompanySalesInvoiceLine.objects.create(
            invoice=invoice, line_no=1, item_code="A", quantity_invoiced=Decimal("10"),
            unit_price=Decimal("11"), line_total=Decimal("100"),
        )
        case = Transaction.objects.create(customer=customer, currency="PHP")
        case.purchase_orders.add(order)
        case.delivery_receipts.add(receipt)
        case.sales_invoices.add(invoice)
        with self.assertRaises(ValidationError):
            DocumentMatch.objects.create(
                transaction=case, purchase_order_line=order_line,
                delivery_receipt_line=receipt_line, invoice_line=invoice_line,
                matched_quantity=Decimal("10"), match_status="matched",
            )
        invoice_line.unit_price = Decimal("10")
        invoice_line.save()
        DocumentMatch.objects.create(
            transaction=case, purchase_order_line=order_line,
            delivery_receipt_line=receipt_line, invoice_line=invoice_line,
            matched_quantity=Decimal("10"), match_status="matched",
        )
        payment = CustomerPayment.objects.create(
            customer=customer, payment_reference_no="PAY1", currency="PHP",
            amount_received=Decimal("40"), payment_status="cleared",
        )
        PaymentAllocation.objects.create(payment=payment, invoice=invoice, cash_amount=Decimal("40"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.payment_status, "partially_paid")
        self.assertEqual(invoice.outstanding_balance, Decimal("60"))

    def test_database_import_key_prevents_duplicate_invoice(self):
        source = DatabaseSource.objects.create(
            name="ERP", host="localhost", database_name="erp", username="reader",
        )
        run = ExtractionRun.objects.create(source=source)
        schema = DatabaseSchema.objects.create(run=run, name="public")
        table = DatabaseTable.objects.create(schema=schema, name="invoices")
        customer = Customer.objects.create(customer_code="C2", customer_name="Customer")
        CompanySalesInvoice.objects.create(
            customer=customer, source_database=source, source_table=table,
            source_record_key={"invoice_id": 42}, currency="PHP",
        )
        with self.assertRaises(ValidationError):
            CompanySalesInvoice.objects.create(
                customer=customer, source_database=source, source_table=table,
                source_record_key={"invoice_id": 42}, currency="PHP",
            )
