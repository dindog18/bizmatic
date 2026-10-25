"""Plain functions for AR matching and settlement; models remain ordinary models.Model classes."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum

from .amounts import line_amount_difference, line_amount_issues

if TYPE_CHECKING:
    from ..models import (
        CustomerPurchaseOrder,
        CompanyDeliveryReceipt,
        CompanySalesInvoice,
        CustomerPayment,
        CustomerPurchaseOrderLine,
        CompanyDeliveryReceiptLine,
        CompanySalesInvoiceLine,
        Transaction,
        DocumentMatch,
        PaymentAllocation,
    )

    type SourceRecord = (
        CustomerPurchaseOrder | CompanyDeliveryReceipt | CompanySalesInvoice | CustomerPayment
    )
    type CaseDocument = CustomerPurchaseOrder | CompanyDeliveryReceipt | CompanySalesInvoice
    type DocumentLine = CustomerPurchaseOrderLine | CompanyDeliveryReceiptLine | CompanySalesInvoiceLine

ZERO = Decimal("0")
PRICE_TOLERANCE = Decimal(str(getattr(settings, "RECONCILIATION_PRICE_TOLERANCE", "0.01")))


def normalize_source_key(key):
    # Sorting composite keys ensures repeat imports use the same stored identity.
    return json.loads(json.dumps(key, sort_keys=True)) if key else key


def refresh_document_cases(document: CaseDocument) -> None:
    # Changing a source document can invalidate an existing match.
    for case in document.reconciliation_cases.all():
        case.refresh_reconciliation_status()


def validate_source(record: SourceRecord) -> None:
    """Ensure the database table and extraction logs belong to the chosen sources."""
    errors = {}
    if record.source_table_id:
        if (
            not record.source_database_id
            or record.source_table.schema.run.source_id != record.source_database_id
        ):
            errors["source_table"] = "Source table must belong to the selected database."
        if not record.source_record_key:
            errors["source_record_key"] = "Record key is required for a database table source."
        elif (
            type(record)
            .objects.filter(
                source_table_id=record.source_table_id, source_record_key=record.source_record_key
            )
            .exclude(pk=record.pk)
            .exists()
        ):
            errors["source_record_key"] = "This source record was imported already."
    for field in ("source_llm_log", "source_text_log"):
        log = getattr(record, field)
        if log and (
            not record.source_document_id or log.fk_document_no_id != record.source_document_id
        ):
            errors[field] = "Extraction log must belong to the source document."
    if errors:
        raise ValidationError(errors)


def validate_line(line: DocumentLine) -> None:
    """Keep quantities and prices stable while a line participates in a completed match."""
    if not line.pk or not line.matches.filter(match_status="matched").exists():
        return
    previous = type(line).objects.get(pk=line.pk)
    protected = (
        "purchase_order_id",
        "delivery_receipt_id",
        "invoice_id",
        "line_no",
        "item_code",
        "unit_of_measure",
        "quantity_ordered",
        "quantity_accepted",
        "quantity_invoiced",
        "unit_price",
        "discount_amount",
        "tax_amount",
        "line_total",
    )
    if any(
        (
            hasattr(line, name) and getattr(line, name) != getattr(previous, name)
            for name in protected
        )
    ):
        raise ValidationError("Remove existing matches before changing matched line values.")


def validate_match(match: DocumentMatch) -> None:
    """Check three-way matching rules and prevent reuse of ordered or accepted quantities."""
    errors = {}
    if not match.transaction_id or not match.invoice_line_id:
        return
    case = match.transaction
    invoice = match.invoice_line.invoice
    if not case.customer_id:
        errors["transaction"] = "Set the case customer or supplier before matching."
    if invoice.customer_id != case.customer_id or invoice.currency != case.currency:
        errors["invoice_line"] = "Invoice party and currency must match the case."
    if not case.sales_invoices.filter(pk=invoice.pk).exists():
        errors["invoice_line"] = "Add the invoice to the case first."
    for field, collection, header in (
        ("purchase_order_line", "purchase_orders", "purchase_order"),
        ("delivery_receipt_line", "delivery_receipts", "delivery_receipt"),
    ):
        line = getattr(match, field)
        if line is None:
            continue
        document = getattr(line, header)
        if document.customer_id != case.customer_id:
            errors[field] = "Document party must match the case."
        elif hasattr(document, "currency") and document.currency != case.currency:
            errors[field] = "Document currency must match the case."
        elif not getattr(case, collection).filter(pk=document.pk).exists():
            errors[field] = "Add this document to the case first."
    if match.match_status == match.Status.MATCHED and (
        not match.purchase_order_line_id
        or not match.delivery_receipt_line_id
        or match.matched_quantity <= ZERO
    ):
        errors["match_status"] = (
            "A matched line needs an order, an accepted receipt, and a positive quantity."
        )
    order_line = match.purchase_order_line
    receipt_line = match.delivery_receipt_line
    if (
        match.match_status == match.Status.MATCHED
        and order_line is not None
        and (receipt_line is not None)
    ):
        invoice_line = match.invoice_line
        for line, quantity_field, field in (
            (invoice_line, "quantity_invoiced", "invoice_line"),
            (order_line, "quantity_ordered", "purchase_order_line"),
        ):
            issues = line_amount_issues(line, quantity_field, PRICE_TOLERANCE)
            if issues:
                errors[field] = "; ".join(issues)
        if not invoice.invoice_reference_no or not invoice.invoice_date or (not invoice.currency):
            errors["invoice_line"] = (
                "Invoice reference, date, and currency are required for matching."
            )
        if (
            not receipt_line.delivery_receipt.dr_reference_no
            or not receipt_line.delivery_receipt.delivery_date
        ):
            errors["delivery_receipt_line"] = (
                "Delivery reference and date are required for matching."
            )
        if order_line.purchase_order.status == "cancelled":
            errors["purchase_order_line"] = "A cancelled purchase order cannot be matched."
        if (
            abs(order_line.unit_price - invoice_line.unit_price) * match.matched_quantity
            > PRICE_TOLERANCE
        ):
            errors["invoice_line"] = "Invoiced unit price differs from the purchase order."
        if order_line.quantity_ordered and invoice_line.quantity_invoiced:
            order_discount = order_line.discount_amount / order_line.quantity_ordered
            invoice_discount = invoice_line.discount_amount / invoice_line.quantity_invoiced
            order_tax = order_line.tax_amount / order_line.quantity_ordered
            invoice_tax = invoice_line.tax_amount / invoice_line.quantity_invoiced
            if abs(order_discount - invoice_discount) * match.matched_quantity > PRICE_TOLERANCE:
                errors["invoice_line"] = "Invoiced discount differs from the purchase order."
            if abs(order_tax - invoice_tax) * match.matched_quantity > PRICE_TOLERANCE:
                errors["invoice_line"] = "Invoiced tax differs from the purchase order."
        if (
            order_line.unit_of_measure
            and invoice_line.unit_of_measure
            and (order_line.unit_of_measure.casefold() != invoice_line.unit_of_measure.casefold())
        ):
            errors["invoice_line"] = "Unit of measure differs from the order."
        if (
            order_line.item_code
            and invoice_line.item_code
            and (order_line.item_code.casefold() != invoice_line.item_code.casefold())
        ):
            errors["invoice_line"] = "Item code differs from the order."
        if (
            receipt_line.item_code
            and invoice_line.item_code
            and (receipt_line.item_code.casefold() != invoice_line.item_code.casefold())
        ):
            errors["delivery_receipt_line"] = "Received item differs from the invoice."
    if match.match_status == match.Status.MATCHED and match.matched_quantity > ZERO:
        for field, capacity in (
            ("invoice_line", "quantity_invoiced"),
            ("purchase_order_line", "quantity_ordered"),
            ("delivery_receipt_line", "quantity_accepted"),
        ):
            line = getattr(match, field)
            if line is None:
                continue
            used = (
                type(match)
                .objects.filter(**{field: line}, match_status=match.Status.MATCHED)
                .exclude(pk=match.pk)
                .aggregate(total=Sum("matched_quantity"))["total"]
                or ZERO
            )
            if used + match.matched_quantity > getattr(line, capacity):
                errors[field] = "Matched quantity exceeds the available quantity."
    if errors:
        raise ValidationError(errors)


def validate_allocation(allocation: PaymentAllocation) -> None:
    """Keep allocations within the payment components and invoice total."""
    if not allocation.payment_id or not allocation.invoice_id:
        return
    payment, invoice = (allocation.payment, allocation.invoice)
    errors = {}
    if payment.payment_status == "reversed":
        errors["payment"] = "A reversed payment cannot be allocated."
    if (
        allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
        <= ZERO
    ):
        errors["cash_amount"] = "Allocate a positive amount."
    if payment.customer_id != invoice.customer_id or payment.currency != invoice.currency:
        errors["invoice"] = "Invoice party and currency must match the payment."
    if not payment.payment_reference_no or not payment.currency or (not payment.customer_id):
        errors["payment"] = "Payment reference, party, and currency are required for allocation."
    if not invoice.invoice_reference_no or not invoice.currency or (not invoice.customer_id):
        errors["invoice"] = "Invoice reference, party, and currency are required for allocation."
    others = type(allocation).objects.filter(payment=payment).exclude(pk=allocation.pk)
    for field, limit in (
        ("cash_amount", payment.amount_received),
        ("withholding_tax_amount", payment.withholding_tax_amount),
        ("discount_amount", payment.discount_taken),
    ):
        used = others.aggregate(total=Sum(field))["total"] or ZERO
        if used + getattr(allocation, field) > limit:
            errors[field] = "Allocated amount exceeds the payment amount."
    invoice_others = (
        type(allocation)
        .objects.filter(invoice=invoice)
        .exclude(pk=allocation.pk)
        .exclude(payment__payment_status="reversed")
    )
    allocated = sum(
        (
            row.cash_amount + row.withholding_tax_amount + row.discount_amount
            for row in invoice_others
        )
    )
    if (
        allocated
        + allocation.cash_amount
        + allocation.withholding_tax_amount
        + allocation.discount_amount
        > invoice.total_amount
    ):
        errors["invoice"] = "Total allocations exceed the invoice amount."
    if errors:
        raise ValidationError(errors)


def validate_invoice_allocations(invoice: CompanySalesInvoice) -> None:
    """Prevent reducing an invoice below the amounts already allocated to it."""
    if invoice.pk:
        allocations = invoice.payment_allocations.exclude(payment__payment_status="reversed")
        allocated = sum(
            (
                row.cash_amount + row.withholding_tax_amount + row.discount_amount
                for row in allocations
            ),
            ZERO,
        )
        if allocated > invoice.total_amount:
            raise ValidationError({"total_amount": "Invoice total is below its allocations."})


def settled_amount(invoice: CompanySalesInvoice) -> Decimal:
    """Total the cash, withholding tax, and discounts from cleared payments."""
    return sum(
        (
            allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
            for allocation in invoice.payment_allocations.select_related("payment")
            if allocation.payment.payment_status == "cleared"
        ),
        ZERO,
    )


def validate_payment_amounts(payment: CustomerPayment) -> None:
    """Prevent reducing payment amounts below their existing allocations."""
    if not payment.pk:
        return
    for allocation_field, payment_field in (
        ("cash_amount", "amount_received"),
        ("withholding_tax_amount", "withholding_tax_amount"),
        ("discount_amount", "discount_taken"),
    ):
        allocated = (
            payment.invoice_allocations.aggregate(total=Sum(allocation_field))["total"] or ZERO
        )
        if allocated > getattr(payment, payment_field):
            raise ValidationError({payment_field: "Payment amount is below its allocations."})


def unallocated_cash(payment: CustomerPayment) -> Decimal:
    """Return the cash remaining for allocation to other invoices."""
    allocated = payment.invoice_allocations.aggregate(total=Sum("cash_amount"))["total"] or ZERO
    return max(ZERO, payment.amount_received - allocated)


def calculate_reconciliation(case: Transaction) -> tuple[str, Decimal]:
    """Compare document totals and invoice line coverage to classify the case."""
    if not case.pk:
        return ("pending", ZERO)
    invoices = list(case.sales_invoices.all())
    invoice_lines = [line for invoice in invoices for line in invoice.lines.all()]
    covered_any = False
    all_covered = bool(invoice_lines)
    discrepancy = ZERO
    invalid_amounts = False
    for order in case.purchase_orders.all():
        order_lines = list(order.lines.all())
        charges = ZERO
        expected_total = order.subtotal - order.discount_amount + order.tax_amount + charges
        line_total = sum((line.line_total for line in order_lines), ZERO) + charges
        header_difference = abs(order.total_amount - expected_total)
        line_difference = abs(order.total_amount - line_total)
        if header_difference > PRICE_TOLERANCE:
            discrepancy += header_difference
        if line_difference > PRICE_TOLERANCE:
            discrepancy += line_difference
        for line in order_lines:
            if line_amount_issues(line, "quantity_ordered", PRICE_TOLERANCE):
                invalid_amounts = True
                discrepancy += line_amount_difference(line, "quantity_ordered")
    for invoice in invoices:
        expected_total = invoice.subtotal - invoice.discount_amount + invoice.tax_amount + ZERO
        header_difference = abs(invoice.total_amount - expected_total)
        line_difference = abs(
            invoice.total_amount
            - (sum((line.line_total for line in invoice.lines.all()), ZERO) + ZERO)
        )
        if header_difference > PRICE_TOLERANCE:
            discrepancy += header_difference
        if line_difference > PRICE_TOLERANCE:
            discrepancy += line_difference
        if invoice.invoice_status == "void":
            discrepancy += invoice.total_amount
    for line in invoice_lines:
        covered = (
            case.line_matches.filter(invoice_line=line, match_status="matched").aggregate(
                total=Sum("matched_quantity")
            )["total"]
            or ZERO
        )
        covered_any = covered_any or covered > ZERO
        all_covered = all_covered and line.quantity_invoiced > ZERO and covered == line.quantity_invoiced
        if line_amount_issues(line, "quantity_invoiced", PRICE_TOLERANCE):
            invalid_amounts = True
            discrepancy += line_amount_difference(line, "quantity_invoiced")
        elif covered < line.quantity_invoiced:
            discrepancy += (line.quantity_invoiced - covered) * line.unit_price
    invalid_match = False
    for match in case.line_matches.filter(match_status="matched"):
        try:
            match.clean()
        except ValidationError:
            invalid_match = True
            # Arithmetic discrepancies were counted above, including legacy saved matches.
            if not (line_amount_issues(match.invoice_line, "quantity_invoiced", PRICE_TOLERANCE)
                    or (match.purchase_order_line and line_amount_issues(match.purchase_order_line, "quantity_ordered", PRICE_TOLERANCE))):
                discrepancy += match.invoice_line.unit_price * match.matched_quantity
    has_exception = (
        invalid_match
        or invalid_amounts
        or case.line_matches.filter(match_status="exception").exists()
        or any((invoice.invoice_status == "void" for invoice in invoices))
    )
    if has_exception or (discrepancy > PRICE_TOLERANCE and all_covered):
        status = "exception"
    elif all_covered:
        status = "matched"
    elif covered_any:
        status = "partial"
    else:
        status = "pending"
    with localcontext() as amount_context:
        amount_context.prec = 40
        discrepancy = discrepancy.quantize(Decimal("0.01"))
    # Return a validation message rather than persisting an unreadable monetary value.
    case._meta.get_field("total_discrepancy_amount").clean(discrepancy, case)
    return (status, discrepancy)


def validate_case(case: Transaction) -> None:
    """Prevent manually marking an incomplete or discrepant case as matched."""
    if (
        case.pk
        and case.reconciliation_status == "matched"
        and (case.calculate_reconciliation()[0] != "matched")
    ):
        raise ValidationError(
            {"reconciliation_status": "The case still has unmatched or discrepant invoice lines."}
        )
