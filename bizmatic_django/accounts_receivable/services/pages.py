"""Serialize saved accounting records for the existing workspace screens."""

import json
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from db_extraction.models import DatabaseSource, DatabaseTable
from .amounts import line_amount_issues
from .catalog import model, party_key, RESOURCES, revision
from .configuration import snapshot
from .records import allocations, case_membership, matches


def number(value):
    return float(value or 0)


def text_date(value):
    return value.isoformat() if value else ""


def party(row, mode):
    key = party_key(mode)
    return {"id": row.pk, "reference": getattr(row, key+"_code"), "name": getattr(row, key+"_name"),
            "taxId": row.tax_identification_no, "address": row.billing_address, "contact": row.contact_person,
            "email": row.email, "phone": row.phone, "terms": row.payment_terms_days, "notes": row.llm_context,
            "status": "active" if row.is_active else "inactive", "creditLimit": number(getattr(row, "credit_limit", 0)),
            "shippingAddress": getattr(row, "shipping_address", ""), "revision": revision(row)}


def line(row):
    quantity = getattr(row, "quantity_ordered", getattr(row, "quantity_invoiced", getattr(row, "quantity_stated", 0)))
    price = getattr(row, "unit_price", Decimal("0"))
    discount = getattr(row, "discount_amount", Decimal("0"))
    base = quantity * price - discount
    tax = getattr(row, "tax_amount", Decimal("0"))
    quantity_field = "quantity_ordered" if hasattr(row, "quantity_ordered") else "quantity_invoiced"
    tolerance = Decimal(str(getattr(settings, "RECONCILIATION_PRICE_TOLERANCE", "0.01")))
    amount_issues = line_amount_issues(row, quantity_field, tolerance) if hasattr(row, "unit_price") else []
    return {"id": row.pk, "code": row.item_code, "description": row.description, "unit": row.unit_of_measure,
            "quantity": number(quantity), "price": number(price), "discount": number(discount),
            "tax": number(tax), "total": number(getattr(row, "line_total", 0)), "taxRate": number(tax / base * 100) if base else 0,
            "amountIssues": amount_issues,
            "received": number(getattr(row, "quantity_received", 0)), "accepted": number(getattr(row, "quantity_accepted", 0)), "rejected": number(getattr(row, "quantity_rejected", 0))}


def document(row, target, mode):
    ref = {"purchase_order": "po_reference_no", "delivery_receipt": "dr_reference_no", "sales_invoice": "invoice_reference_no", "payment": "payment_reference_no"}[target]
    date = {"purchase_order": "order_date", "delivery_receipt": "delivery_date", "sales_invoice": "invoice_date", "payment": "payment_date"}[target]
    status = {"purchase_order": "status", "delivery_receipt": "delivery_status" if mode == "ar" else "receipt_status", "sales_invoice": "payment_status", "payment": "payment_status"}[target]
    source = "document" if row.source_document_id else "database" if row.source_database_id else ""
    result = {"id": row.pk, "reference": getattr(row, ref) or f"#{row.pk}", "partyId": getattr(row, party_key(mode)+"_id"),
              "date": text_date(getattr(row, date)), "currency": getattr(row, "currency", ""), "status": getattr(row, status),
              "amount": number(getattr(row, "total_amount", getattr(row, "amount_received" if mode == "ar" else "amount_paid", 0))),
              "subtotal": number(getattr(row, "subtotal", 0)), "discount": number(getattr(row, "discount_amount", 0)),
              "tax": number(getattr(row, "tax_amount", 0)), "otherCharges": number(getattr(row, "other_charges", 0)),
              "dueDate": text_date(getattr(row, "due_date", None)), "expectedDate": text_date(getattr(row, "expected_delivery_date", None)),
              "receivedBy": getattr(row, "received_by", ""), "receivedDate": text_date(getattr(row, "received_at", getattr(row, "received_date", None))),
              "location": getattr(row, "delivery_address", getattr(row, "delivery_location", "")),
              "invoiceStatus": getattr(row, "invoice_status", ""), "withholding": number(getattr(row, "withholding_tax_amount", 0)),
              "discountTaken": number(getattr(row, "discount_taken", 0)), "method": getattr(row, "payment_method", ""),
              "bankReference": getattr(row, "bank_reference_no", ""), "postingDate": text_date(getattr(row, "posting_date", None)),
              "clearedAt": text_date(getattr(row, "cleared_at", None)), "reversedAt": text_date(getattr(row, "reversed_at", None)),
              "reversalReason": getattr(row, "reversal_reason", ""), "notes": getattr(row, "notes", ""),
              "source": source, "sourceName": row.source_document.file_name if row.source_document_id else f"{row.source_table.schema.name}.{row.source_table.name}" if row.source_table_id else "",
              "sourceUrl": f"/documents/{row.source_document_id}/" if row.source_document_id else f"/databases/{row.source_database_id}/" if row.source_database_id else "/documents/",
              "databaseName": row.source_database.name if row.source_database_id else "", "sourceKey": json.dumps(row.source_record_key),
              "textLog": row.source_text_log_id, "llmLog": row.source_llm_log_id, "importedAt": text_date(row.imported_at),
              "lines": [line(item) for item in row.lines.order_by("line_no", "pk")] if target != "payment" else [],
              "revision": revision(row, allocations(row)) if target == "payment" else revision(row)}
    if target == "sales_invoice":
        result["settled"] = number(row.settled_amount)
        result["balance"] = number(row.outstanding_balance)
    return result


def configuration(row, mode):
    values = snapshot(row)
    source = row.source_schema_snapshot
    return {**values, "id": row.pk, "scope": str(getattr(row, party_key(mode)+"_id") or "module"),
            "connection": source.get("connection", ""), "table": source.get("header_table", ""),
            "columns": "\n".join(source.get("header_columns", [])), "source_keys": ", ".join(row.source_key_fields),
            "line_table": source.get("line_table", ""), "line_columns": "\n".join(source.get("line_columns", [])),
            "line_joins": ", ".join(pair["header_column"]+"="+pair["line_column"] for pair in row.line_join_fields),
            "include_lines": bool(row.line_source_table_id), "assistant_messages": row.assistant_messages,
            "assistant_proposal": row.assistant_proposal or None, "status": row.status,
            "submitted_snapshot": row.submitted_snapshot or None, "submitted_at": text_date(row.submitted_at)}


def llm_log(row):
    result = {field.name: field.value_from_object(row) for field in row._meta.fields}
    result["revision"] = row.updated_at.isoformat()
    result["preview_reference"] = {"record_label": row.configuration.name if row.configuration_id else row.target_entity,
                                   "source_name": row.fk_document_no.file_name if row.fk_document_no_id else "Configuration"}
    return result


def workspace_state(mode, resource):
    state = {"parties": [party(row, mode) for row in model(mode, party_key(mode)).objects.all()], "today": timezone.localdate().isoformat()}
    if resource == "configuration":
        from document_extraction.models import DocExtractionLog
        state["sample_documents"] = list(DocExtractionLog.objects.exclude(markdown_text="").order_by("-pk").values("pk", "fk_document_no__file_name")[:50])
        state["profiles"] = [configuration(row, mode) for row in model(mode, "ExtractionConfiguration").objects.all()]
        state["import_runs"] = list(model(mode, "DatabaseImportRun").objects.values("id", "configuration_id", "status", "result", "created_at")[:50])
        state["sources"] = list(DatabaseSource.objects.filter(enabled=True).values("id", "name"))
        state["tables"] = [{"id": row.pk, "source_id": row.schema.run.source_id, "label": f"{row.schema.name}.{row.name} · snapshot #{row.schema.run_id}", "name": f"{row.schema.name}.{row.name}", "columns": list(row.columns.values_list("name", flat=True))} for row in DatabaseTable.objects.filter(schema__run__status="completed").select_related("schema__run").prefetch_related("columns")]
        return state
    if resource == "llm-logs":
        state["logs"] = [llm_log(row) for row in model(mode, "LLMExtractionLog").objects.select_related("configuration", "fk_document_no").all()]
        return state
    for resource_name, target in RESOURCES.items():
        rows = model(mode, target).objects.select_related("source_document", "source_database", "source_table__schema")
        state[resource_name] = [document(row, target, mode) for row in rows]
    state["allocations"] = [{"paymentId": row.payment_id, "invoiceId": row.invoice_id, "cash": number(row.cash_amount), "withholding": number(row.withholding_tax_amount), "discount": number(row.discount_amount)} for row in model(mode, "PaymentAllocation").objects.all()]
    indexes = {key: {line["id"]: (row["id"], index) for row in state[key] for index, line in enumerate(row["lines"])} for key in ("purchase-orders", "delivery-receipts", "invoices")}
    amount_issues = {key: {line["id"]: line["amountIssues"] for row in state[key] for line in row["lines"]}
                     for key in ("purchase-orders", "invoices")}
    state["reconciliation"] = []
    for row in model(mode, "Transaction").objects.all():
        membership = case_membership(row)
        calculation_issue = ""
        try:
            status, discrepancy = row.calculate_reconciliation()
        except ValidationError as error:
            status, discrepancy = "exception", None
            calculation_issue = "; ".join(error.messages)
        comparisons = []
        for match in row.line_matches.all():
            invoice, invoice_index = indexes["invoices"][match.invoice_line_id]
            order, order_index = indexes["purchase-orders"].get(match.purchase_order_line_id, (None, None))
            receipt, receipt_index = indexes["delivery-receipts"].get(match.delivery_receipt_line_id, (None, None))
            match_status = match.match_status
            if match_status == "matched" and (amount_issues["invoices"].get(match.invoice_line_id)
                                               or amount_issues["purchase-orders"].get(match.purchase_order_line_id)):
                match_status = "exception"
            comparisons.append({"invoiceId": invoice, "invoiceLine": invoice_index, "orderId": order, "orderLine": order_index, "receiptId": receipt, "receiptLine": receipt_index, "quantity": number(match.matched_quantity), "status": match_status})
        # Recheck old saved cases on read without rewriting source records or cached decisions.
        state["reconciliation"].append({"id": row.pk, "reference": f"{mode.upper()}-{row.pk}", "partyId": getattr(row, party_key(mode)+"_id"), "date": text_date(row.transaction_date), "currency": row.currency, "notes": row.notes, "status": status, "discrepancy": number(discrepancy) if discrepancy is not None else None, "calculationIssue": calculation_issue, "reconciledAt": text_date(row.reconciled_at), "orderIds": membership["purchase_orders"], "receiptIds": membership["delivery_receipts"], "invoiceIds": membership["sales_invoices"], "matches": comparisons, "revision": revision(row, membership), "matchRevision": revision(row, [membership, matches(row)])})
    return state
