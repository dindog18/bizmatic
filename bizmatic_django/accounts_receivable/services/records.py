"""Save accounts, reconciliation cases, matches, and allocations atomically."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from .catalog import check_revision, model, party_key, revision


def case_membership(case):
    return {name: list(getattr(case, name).order_by("pk").values_list("pk", flat=True))
            for name in ("purchase_orders", "delivery_receipts", "sales_invoices")}


def allocations(payment):
    return list(payment.invoice_allocations.order_by("pk").values("invoice_id", "cash_amount", "withholding_tax_amount", "discount_amount"))


def matches(case):
    return list(case.line_matches.order_by("pk").values("invoice_line_id", "purchase_order_line_id", "delivery_receipt_line_id", "matched_quantity", "match_status"))


@transaction.atomic
def save_party(mode, data, record_id=None):
    record = get_object_or_404(model(mode, party_key(mode)).objects.select_for_update(), pk=record_id) if record_id else model(mode, party_key(mode))()
    if record_id:
        check_revision(record, data.get("revision"))
    mapping = {"reference": party_key(mode)+"_code", "name": party_key(mode)+"_name", "taxId": "tax_identification_no",
               "address": "billing_address", "contact": "contact_person", "email": "email", "phone": "phone",
               "terms": "payment_terms_days", "notes": "llm_context"}
    if mode == "ar":
        mapping.update(shippingAddress="shipping_address", creditLimit="credit_limit")
    for key, field in mapping.items():
        if key in data:
            setattr(record, field, data[key])
    if data.get("status") not in {"active", "inactive"}:
        raise ValidationError("Choose an account status.")
    record.is_active = data["status"] == "active"
    record.full_clean()
    record.save()
    return record


@transaction.atomic
def save_case(mode, data, record_id=None):
    account = get_object_or_404(model(mode, party_key(mode)).objects.select_for_update(), pk=data.get("partyId"))
    case = get_object_or_404(model(mode, "Transaction").objects.select_for_update(), pk=record_id) if record_id else model(mode, "Transaction")()
    if record_id:
        check_revision(case, data.get("revision"), case_membership(case))
        if getattr(case, party_key(mode)+"_id") != account.pk:
            raise ValidationError("Create a new case to change the account.")
    selected = {}
    for key, relation, target in [("orderIds", "purchase_orders", "purchase_order"), ("receiptIds", "delivery_receipts", "delivery_receipt"), ("invoiceIds", "sales_invoices", "sales_invoice")]:
        ids = data.get(key, [])
        if not isinstance(ids, list) or any(type(pk) is not int for pk in ids) or len(ids) != len(set(ids)):
            raise ValidationError("Choose valid document IDs without duplicates.")
        rows = list(model(mode, target).objects.select_for_update().filter(pk__in=ids).order_by("pk"))
        if len(rows) != len(ids) or any(getattr(row, party_key(mode)+"_id") != account.pk or (hasattr(row, "currency") and row.currency != data.get("currency")) for row in rows):
            raise ValidationError("Case documents must have the same account and currency.")
        selected[relation] = rows
    if not selected["sales_invoices"]:
        raise ValidationError("Link at least one invoice.")
    if case.pk:
        # Membership edits invalidate saved comparisons; they must be reviewed again.
        changed = any(set(getattr(case, key).values_list("pk", flat=True)) != {row.pk for row in rows} for key, rows in selected.items())
        if changed:
            case.line_matches.all().delete()
    setattr(case, party_key(mode), account)
    case.transaction_date = data.get("date")
    case.currency = data.get("currency")
    case.notes = data.get("notes", "")
    case.reconciliation_status = "pending"
    case.save()
    for key, rows in selected.items():
        getattr(case, key).set(rows)
    case.refresh_reconciliation_status()
    return case


@transaction.atomic
def save_allocations(mode, record_id, data):
    payment = get_object_or_404(model(mode, "payment"), pk=record_id)
    # Account lock serializes all allocations for this account before invoice locks.
    model(mode, party_key(mode)).objects.select_for_update().get(pk=getattr(payment, party_key(mode)+"_id"))
    payment = model(mode, "payment").objects.select_for_update().get(pk=record_id)
    check_revision(payment, data.get("revision"), allocations(payment))
    if payment.payment_status == "reversed":
        raise ValidationError("Reversed payments cannot be allocated.")
    rows = data.get("allocations")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValidationError("Provide up to 1,000 allocations.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValidationError("Each allocation must be an object containing its field values.")
    old_ids = set(payment.invoice_allocations.values_list("invoice_id", flat=True))
    seen = set()
    payment.invoice_allocations.all().delete()
    for row in rows:
        invoice_id = row.get("invoiceId")
        if type(invoice_id) is not int or invoice_id in seen:
            raise ValidationError("Choose each invoice once.")
        seen.add(invoice_id)
        invoice = get_object_or_404(model(mode, "sales_invoice").objects.select_for_update(), pk=invoice_id)
        if invoice.invoice_status in {"draft", "pending", "void"}:
            raise ValidationError("Only posted or disputed invoices can receive allocations.")
        allocation = model(mode, "PaymentAllocation")(
            payment=payment, invoice=invoice, cash_amount=row.get("cash", "0"),
            withholding_tax_amount=row.get("withholding", "0"), discount_amount=row.get("discount", "0"))
        allocation.save()  # Existing model validates account, currency and component limits.
    for invoice in model(mode, "sales_invoice").objects.filter(pk__in=old_ids | seen):
        invoice.refresh_payment_status()
    return payment


@transaction.atomic
def save_matches(mode, record_id, data):
    case = get_object_or_404(model(mode, "Transaction"), pk=record_id)
    model(mode, party_key(mode)).objects.select_for_update().get(pk=getattr(case, party_key(mode)+"_id"))
    case = model(mode, "Transaction").objects.select_for_update().get(pk=record_id)
    check_revision(case, data.get("revision"), [case_membership(case), matches(case)])
    rows = data.get("matches")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValidationError("Provide up to 1,000 line matches.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValidationError("Each line match must be an object containing its field values.")
    case.line_matches.all().delete()
    seen = set()
    for row in rows:
        invoice_id = row.get("invoiceLineId")
        if type(invoice_id) is not int or invoice_id in seen:
            raise ValidationError("Choose each invoice line once.")
        seen.add(invoice_id)
        match = model(mode, "DocumentMatch")(
            transaction=case, invoice_line_id=invoice_id,
            purchase_order_line_id=row.get("orderLineId"), delivery_receipt_line_id=row.get("receiptLineId"),
            matched_quantity=row.get("quantity", "0"), match_status="pending")
        match.full_clean()
        if match.purchase_order_line_id and match.delivery_receipt_line_id and Decimal(str(match.matched_quantity)) > 0:
            match.match_status = "matched"
            try:
                match.full_clean()
            except ValidationError:
                match.match_status = "exception"
        match.save()
    case.refresh_reconciliation_status()
    return case
