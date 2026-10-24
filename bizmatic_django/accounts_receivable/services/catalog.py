"""Small AP/AR model map shared by the two workspaces."""

import hashlib
import json

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder

MODULES = {"ap": "accounts_payable", "ar": "accounts_receivable"}
TARGETS = {
    "ap": {"supplier": "Supplier", "purchase_order": "CompanyPurchaseOrder",
           "delivery_receipt": "SupplierDeliveryReceipt", "sales_invoice": "SupplierSalesInvoice", "payment": "CompanyPayment"},
    "ar": {"customer": "Customer", "purchase_order": "CustomerPurchaseOrder",
           "delivery_receipt": "CompanyDeliveryReceipt", "sales_invoice": "CompanySalesInvoice", "payment": "CustomerPayment"},
}
RESOURCES = {"purchase-orders": "purchase_order", "delivery-receipts": "delivery_receipt",
             "invoices": "sales_invoice", "payments": "payment"}


def model(mode, name):
    return apps.get_model(MODULES[mode], TARGETS[mode].get(name, name))


def party_key(mode):
    return "customer" if mode == "ar" else "supplier"


def fields(mode, target, lines=False):
    """Only user-configurable values; provenance and parent IDs are server-owned."""
    record = model(mode, target)
    if lines:
        record = model(mode, record.__name__ + "Line")
    excluded = {"created_at", "updated_at", "imported_at", "llm_context", "received_items",
                "proof_of_delivery", "proof_of_payment", "receiving_evidence", "payment_status"}
    if target == "payment":
        excluded.remove("payment_status")
    return [field for field in record._meta.fields if not field.primary_key
            and field.name not in excluded and not field.name.startswith("source_")
            and not field.name.endswith(("_context", "_metadata"))
            and not (lines and field.is_relation)]


def required_fields(mode, target, lines=False):
    """One source of mandatory fields for setup guidance, imports and extraction."""
    required = {field.name for field in fields(mode, target, lines)
                if not field.blank and not field.null and not field.has_default()}
    if not lines and target not in {'customer', 'supplier'}:
        essential = {
            'purchase_order': {'po_reference_no', 'order_date', 'currency', 'total_amount'},
            'delivery_receipt': {'dr_reference_no', 'delivery_date'},
            'sales_invoice': {'invoice_reference_no', 'invoice_date', 'currency', 'total_amount'},
            'payment': {'payment_reference_no', 'payment_date', 'currency', 'amount_received' if mode == 'ar' else 'amount_paid'},
        }
        required.update({party_key(mode), *essential[target]})
    return required


def revision(record, extra=None):
    values = {field.name: field.value_from_object(record) for field in record._meta.fields}
    return hashlib.sha256(json.dumps([values, extra], cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def check_revision(record, value, extra=None):
    if value != revision(record, extra):
        raise ValidationError("This record changed. Reload before saving.", code="conflict")


def error_text(error):
    if isinstance(error, ValidationError):
        return "; ".join(error.messages)
    return str(error)
