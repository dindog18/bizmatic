"""Shared presentation-only routing for the two accounting workspaces.

No business services or database records are read or changed here. Destination
field metadata describes configuration forms. The browser owns synthetic preview
data and session-scoped edits.
"""

from django.apps import apps
from django.shortcuts import render
from django.urls import path, reverse


RESOURCES = (
    ("parties", "party", "Parties", "address-book"),
    ("purchase-orders", "purchase_order", "Purchase orders", "shopping-cart"),
    ("delivery-receipts", "delivery_receipt", "Delivery receipts", "truck"),
    ("invoices", "invoice", "Invoices", "file-invoice-dollar"),
    ("payments", "payment", "Payments", "credit-card"),
    ("reconciliation", "reconciliation", "Reconciliation", "check-double"),
)

# Source documents and payments are populated by extraction, never keyed here.
EDITABLE_RESOURCES = {"parties", "reconciliation"}


def configuration_catalog(mode):
    """Describe destination fields for the form, without querying any records."""
    ar = mode == "ar"
    app = "accounts_receivable" if ar else "accounts_payable"
    definitions = [
        ("customer" if ar else "supplier", "Customers" if ar else "Suppliers", "Customer" if ar else "Supplier", None),
        ("purchase_order", "Purchase orders", "CustomerPurchaseOrder" if ar else "CompanyPurchaseOrder", "CustomerPurchaseOrderLine" if ar else "CompanyPurchaseOrderLine"),
        ("delivery_receipt", "Delivery receipts", "CompanyDeliveryReceipt" if ar else "SupplierDeliveryReceipt", "CompanyDeliveryReceiptLine" if ar else "SupplierDeliveryReceiptLine"),
        ("sales_invoice", "Sales invoices", "CompanySalesInvoice" if ar else "SupplierSalesInvoice", "CompanySalesInvoiceLine" if ar else "SupplierSalesInvoiceLine"),
        ("payment", "Payments", "CustomerPayment" if ar else "CompanyPayment", None),
    ]

    def fields(model_name, lines=False):
        result = []
        excluded = {"created_at", "updated_at", "imported_at", "llm_context", "received_items", "proof_of_delivery", "proof_of_payment", "receiving_evidence"}
        for field in apps.get_model(app, model_name)._meta.fields:
            if field.primary_key or field.name in excluded or field.name.startswith("source_") or field.name.endswith(("_context", "_metadata")):
                continue
            if lines and field.is_relation:
                continue  # Parent relationships are configured through the line join.
            result.append({
                "key": field.name, "label": str(field.verbose_name).capitalize(),
                "type": "lookup" if field.is_relation else field.get_internal_type(),
                "required": not (field.blank or field.null or field.has_default()),
                "choices": list(field.flatchoices) if field.choices else [],
            })
        return result

    return [{"key": key, "label": label, "model": model, "fields": fields(model), "lineModel": line_model, "lineFields": fields(line_model, True) if line_model else []} for key, label, model, line_model in definitions]


def workspace_patterns(view, party_slug):
    """Keep AR/AP route names parallel while using customer/supplier URLs."""
    patterns = [path("", view, name="overview"), path("aging/", view, {"resource": "aging"}, name="aging")]
    for resource, name, _label, _icon in RESOURCES:
        slug = party_slug if resource == "parties" else resource
        patterns.extend([
            path(f"{slug}/", view, {"resource": resource}, name=f"{name}_list"),
            path(f"{slug}/<int:record_id>/", view, {"resource": resource, "screen": "detail"}, name=f"{name}_detail"),
        ])
        if resource in EDITABLE_RESOURCES:
            patterns.extend([
                path(f"{slug}/new/", view, {"resource": resource, "screen": "form"}, name=f"{name}_create"),
                path(f"{slug}/<int:record_id>/edit/", view, {"resource": resource, "screen": "form"}, name=f"{name}_edit"),
            ])
    patterns.extend([
        path("configuration/", view, {"resource": "configuration"}, name="configuration_list"),
        path("configuration/new/", view, {"resource": "configuration", "screen": "configuration"}, name="configuration_create"),
        path("configuration/<int:record_id>/", view, {"resource": "configuration", "screen": "configuration"}, name="configuration_detail"),
        path("payments/<int:record_id>/allocate/", view, {"resource": "payments", "screen": "allocate"}, name="payment_allocate"),
        path("reconciliation/<int:record_id>/match/", view, {"resource": "reconciliation", "screen": "match"}, name="reconciliation_match"),
    ])
    return patterns


def render_workspace(request, mode, resource="overview", screen="list", record_id=None):
    receivable = mode == "ar"
    namespace = "ACCOUNTS_RECEIVABLE" if receivable else "ACCOUNTS_PAYABLE"
    title = "Accounts receivable" if receivable else "Accounts payable"
    party = "Customer" if receivable else "Supplier"
    navigation = [{"key": "overview", "label": "Overview", "icon": "chart-pie", "url": reverse(f"{namespace}:overview")}]
    for key, name, label, icon in RESOURCES:
        navigation.append({"key": key, "label": party + "s" if key == "parties" else label, "icon": icon, "url": reverse(f"{namespace}:{name}_list")})
    navigation.append({"key": "aging", "label": "Aging report", "icon": "clock", "url": reverse(f"{namespace}:aging")})
    navigation.append({"key": "configuration", "label": "Extraction setup", "icon": "sliders-h", "url": reverse(f"{namespace}:configuration_list")})
    label = next((item["label"] for item in navigation if item["key"] == resource), title)
    config = {
        "mode": mode, "title": title, "party": party, "resource": resource,
        "screen": screen, "recordId": record_id,
        "canEncode": resource in EDITABLE_RESOURCES,
        "routes": {item["key"]: item["url"] for item in navigation},
        "configurationCreate": reverse(f"{namespace}:configuration_create"),
        "sources": {
            "documents": reverse("DOC_EXTRACTION:document_list"),
            "upload": reverse("DOC_EXTRACTION:document_upload"),
            "databases": reverse("DB_EXTRACTION:source_list"),
        },
    }
    if resource == "configuration":
        config["configurationCatalog"] = configuration_catalog(mode)
    return render(request, "accounting/workspace.html", {
        "page_title": f"{label} · {title}", "section": "receivables" if receivable else "payables",
        "workspace_name": title, "finance_navigation": navigation, "finance_resource": resource,
        "finance_config": config,
    })
