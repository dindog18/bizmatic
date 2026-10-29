from django.test import Client, TestCase

from accounts_receivable.services.catalog import model, party_key
from accounts_receivable.services.pages import document


class DocumentDeletionTests(TestCase):
    def make_record(self, mode, target):
        key = party_key(mode)
        account, _ = model(mode, key).objects.get_or_create(**{key+'_code': 'DEMO'}, defaults={key+'_name': 'Example'})
        values = {
            'purchase_order': {'po_reference_no': 'PO-1', 'order_date': '2026-10-29', 'currency': 'PHP'},
            'delivery_receipt': {'dr_reference_no': 'DR-1', 'delivery_date': '2026-10-29'},
            'sales_invoice': {'invoice_reference_no': 'SI-1', 'invoice_date': '2026-10-29', 'currency': 'PHP'},
            'payment': {'payment_reference_no': 'PAY-1', 'payment_date': '2026-10-29', 'currency': 'PHP'},
        }[target]
        row = model(mode, target).objects.create(**{key: account}, **values)
        if target != 'payment':
            parent = {'purchase_order': 'purchase_order', 'delivery_receipt': 'delivery_receipt', 'sales_invoice': 'invoice'}[target]
            model(mode, type(row).__name__+'Line').objects.create(**{parent: row}, line_no=1)
        return row

    def payload(self, row, mode, target, resource):
        return {'resource': resource, 'confirmed': True, 'revision': document(row, target, mode)['revision']}

    def test_both_modules_delete_all_four_types_and_retain_attempts(self):
        for mode, slug in [('ap', 'accounts-payable'), ('ar', 'accounts-receivable')]:
            for resource, target in [('purchase-orders', 'purchase_order'), ('delivery-receipts', 'delivery_receipt'), ('invoices', 'sales_invoice'), ('payments', 'payment')]:
                with self.subTest(mode=mode, target=target):
                    row = self.make_record(mode, target)
                    log = model(mode, 'LLMExtractionLog').objects.create(target_entity=target, status='completed', **{target: row})
                    response = self.client.post(f'/{slug}/api/record-delete/{row.pk}/', self.payload(row, mode, target, resource), content_type='application/json')
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertFalse(type(row).objects.filter(pk=row.pk).exists())
                    log.refresh_from_db()
                    self.assertIsNone(getattr(log, target+'_id'))
                    if target != 'payment':
                        self.assertEqual(model(mode, type(row).__name__+'Line').objects.count(), 0)

    def test_confirmation_revision_csrf_and_method_are_required(self):
        row = self.make_record('ar', 'purchase_order')
        url = f'/accounts-receivable/api/record-delete/{row.pk}/'
        payload = self.payload(row, 'ar', 'purchase_order', 'purchase-orders')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, payload, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post(url, {**payload, 'confirmed': False}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {**payload, 'revision': 'stale'}, content_type='application/json').status_code, 409)
        self.assertEqual(self.client.post(url, {**payload, 'resource': 'parties'}, content_type='application/json').status_code, 400)
        self.assertTrue(type(row).objects.filter(pk=row.pk).exists())

    def test_linked_records_and_running_attempts_are_not_deleted(self):
        for mode, slug in [('ap', 'accounts-payable'), ('ar', 'accounts-receivable')]:
            row = self.make_record(mode, 'purchase_order')
            case = model(mode, 'Transaction').objects.create(currency='PHP', **{party_key(mode): getattr(row, party_key(mode))})
            case.purchase_orders.add(row)
            url = f'/{slug}/api/record-delete/{row.pk}/'
            payload = self.payload(row, mode, 'purchase_order', 'purchase-orders')
            self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 400)
            case.purchase_orders.remove(row)
            log = model(mode, 'LLMExtractionLog').objects.create(target_entity='purchase_order', status='processing', purchase_order=row)
            self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 400)
            log.refresh_from_db()
            self.assertEqual(log.purchase_order_id, row.pk)

    def test_allocated_invoices_and_payments_cannot_be_deleted(self):
        for mode, slug in [('ap', 'accounts-payable'), ('ar', 'accounts-receivable')]:
            invoice = self.make_record(mode, 'sales_invoice')
            payment = self.make_record(mode, 'payment')
            type(invoice).objects.filter(pk=invoice.pk).update(invoice_status='posted', subtotal=100, total_amount=100)
            type(payment).objects.filter(pk=payment.pk).update(**{'amount_paid' if mode == 'ap' else 'amount_received': 100})
            invoice.refresh_from_db()
            payment.refresh_from_db()
            allocation = model(mode, 'PaymentAllocation').objects.create(invoice=invoice, payment=payment, cash_amount=10)
            for resource, target, row in [('invoices', 'sales_invoice', invoice), ('payments', 'payment', payment)]:
                row.refresh_from_db()
                response = self.client.post(f'/{slug}/api/record-delete/{row.pk}/', self.payload(row, mode, target, resource), content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
                self.assertTrue(type(row).objects.filter(pk=row.pk).exists())
            self.assertTrue(type(allocation).objects.filter(pk=allocation.pk).exists())
