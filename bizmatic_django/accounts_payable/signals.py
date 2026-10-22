"""Recalculate a case when its document membership changes."""

from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import Transaction


@receiver(m2m_changed, sender=Transaction.purchase_orders.through)
@receiver(m2m_changed, sender=Transaction.delivery_receipts.through)
@receiver(m2m_changed, sender=Transaction.sales_invoices.through)
def document_membership_changed(instance, action, reverse, pk_set, **_kwargs):
    # Reverse changes are made through document.reconciliation_cases.
    if action == "pre_clear" and reverse:
        instance.former_case_ids = list(instance.reconciliation_cases.values_list("pk", flat=True))
        return
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    if not reverse:
        instance.refresh_reconciliation_status()
        return
    case_ids = pk_set if pk_set is not None else getattr(instance, "former_case_ids", [])
    for case in Transaction.objects.filter(pk__in=case_ids):
        case.refresh_reconciliation_status()
