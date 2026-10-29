"""Regression coverage for PR review findings."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts_receivable.services import database_updates
from accounts_receivable.services.catalog import model, party_key
from db_extraction.models import DatabaseSource, ExtractionRun, DatabaseSchema, DatabaseTable


class RetainedLinesTests(TestCase):
    def test_updates_validate_retained_invoice_lines_in_both_modules(self):
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                key = party_key(mode)
                account = model(mode, key).objects.create(**{key+'_code': 'C1', key+'_name': 'Example'})
                source = DatabaseSource.objects.create(name=mode, host='example.test', database_name='test', username='reader')
                run = ExtractionRun.objects.create(source=source, status='completed')
                schema = DatabaseSchema.objects.create(run=run, name='public')
                table = DatabaseTable.objects.create(schema=schema, name='invoices')
                config = model(mode, 'ExtractionConfiguration').objects.create(name='Invoice import', target_entity='sales_invoice',
                    source_type='database', database_source=source, source_table=table,
                    encoding_rules={'required_fields': []}, relation_lookups={key: {'match_field': key+'_code'}})
                invoice = model(mode, 'sales_invoice').objects.create(**{key: account}, invoice_reference_no='INV-1',
                    invoice_date='2026-10-22', currency='PHP', subtotal='100', total_amount='100',
                    invoice_status='pending' if mode == 'ap' else 'draft', source_database=source, source_table=table, source_record_key={'id': 1})
                model(mode, type(invoice).__name__+'Line').objects.create(invoice=invoice, line_no=1,
                    quantity_invoiced='1', unit_price='100', line_total='100')
                parsed = {'record': {key: 'C1', 'invoice_reference_no': 'INV-1', 'invoice_date': '2026-10-22',
                                     'currency': 'PHP', 'subtotal': '200', 'total_amount': '200'}, 'lines': []}
                with self.assertRaisesMessage(ValidationError, 'Header and line totals do not agree'):
                    database_updates.candidate(mode, config, {'id': 1}, parsed)
                parsed['record']['subtotal'] = parsed['record']['total_amount'] = '100'
                _, lines, _, _, _ = database_updates.candidate(mode, config, {'id': 1}, parsed)
                self.assertEqual(len(lines), 1)
