"""Document-extraction targets supported by the accounting modules.

These header models match each app's ExtractionConfiguration.TargetEntity and
accounting configuration catalog. Lines, matches, allocations, and logs belong
to the parent workflow and are not independent routing destinations.
Add another module here when its extraction targets are ready.
"""

from django.apps import apps


MODULES = (
    ("accounts_payable", "Accounts payable", (
        "Supplier", "CompanyPurchaseOrder", "SupplierDeliveryReceipt",
        "SupplierSalesInvoice", "CompanyPayment",
    )),
    ("accounts_receivable", "Accounts receivable", (
        "Customer", "CustomerPurchaseOrder", "CompanyDeliveryReceipt",
        "CompanySalesInvoice", "CustomerPayment",
    )),
)


def destination_catalog():
    """Use real model names and display labels, without reading business records."""
    modules = []
    for app_label, label, model_names in MODULES:
        targets = []
        for model_name in model_names:
            model = apps.get_model(app_label, model_name)
            targets.append({"value": model.__name__, "label": str(model._meta.verbose_name)})
        modules.append({"value": app_label, "label": label, "targets": targets})
    return modules
