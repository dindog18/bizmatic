"""Conversational AP/AR setup never persists configurations before explicit review."""
import json
import os
from unittest.mock import AsyncMock, patch

from django.test import TestCase

from accounts_receivable.services import configuration
from accounts_receivable.services.catalog import model, party_key
from db_extraction.models import DatabaseSource, ExtractionRun, DatabaseSchema, DatabaseTable, DatabaseColumn

class ConfigurationChatTests(TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CONFIG_ASSISTANT_LLM_PROVIDER': 'ollama', 'CONFIG_ASSISTANT_OLLAMA_MODEL': 'setup-test'})
        env.start()
        self.addCleanup(env.stop)
        self.provider = AsyncMock()
        provider = patch('accounts_receivable.services.llm.invoke_with_llm', self.provider)
        provider.start()
        self.addCleanup(provider.stop)

    def values(self, mode='ar'):
        return {'name': '', 'description': '', 'target_entity': 'sales_invoice', 'source_type': 'document',
                party_key(mode): None, 'revision': 1, 'database_source': None, 'source_table': None,
                'line_source_table': None, 'document_type': '', 'extraction_context': '', 'line_item_context': '',
                'sample_text': '', 'encoding_rules': {'default_currency': 'PHP', 'required_fields': [], 'line_required_fields': []},
                'field_mappings': {}, 'line_item_mappings': {}, 'line_join_fields': [], 'source_key_fields': [],
                'relation_lookups': {}, 'field_instructions': {}, 'line_field_instructions': {}}

    def respond(self, result):
        if result.get('updates') == {}:
            result = {key: value for key, value in result.items() if key != 'updates'}
        self.provider.return_value = {'message': {'content': json.dumps(result)}}

    def post(self, mode, action, body, record_id=None):
        browser = self.client
        if 'csrftoken' not in browser.cookies:
            browser.get('/accounts-payable/configuration/new/?target=supplier&source=document')
        if action == 'configuration-chat' and 'selection' not in body:
            body = {**body, 'selection': {key: body['configuration'][key] for key in ('target_entity', 'source_type')}}
        if action == 'configuration-chat':
            history = self.post(mode, 'setup-chat-history', {'selection': body['selection']}).json()
            body = {**body, 'chat_revision': history.get('chat_revision', 0)}
        slug = 'accounts-receivable' if mode == 'ar' else 'accounts-payable'
        return self.client.post(f'/{slug}/api/{action}/' + (f'{record_id}/' if record_id else ''), body, content_type='application/json')

    def complete(self, mode='ar'):
        return {**self.values(mode), 'name': 'Test invoices', 'document_type': 'Invoice',
                'extraction_context': 'Read references, customer codes and totals.', 'line_item_context': 'Read item rows.'}

    def test_reset_forgets_saved_context_and_next_prompt_in_both_modules(self):
        for mode in ('ap', 'ar'):
            for source in ('document', 'database'):
                with self.subTest(mode=mode, source=source):
                    old_topic = 'Big and small customer classification'
                    values = {**self.complete(mode), 'source_type': source, 'name': old_topic,
                              'description': old_topic, 'extraction_context': old_topic,
                              'line_item_context': old_topic, 'sample_text': old_topic,
                              'field_instructions': {'invoice_reference_no': old_topic},
                              'line_field_instructions': {'description': old_topic}}
                    # Seed a saved configuration, including residual context from either source.
                    row = model(mode, 'ExtractionConfiguration').objects.create(**values,
                        assistant_messages=[{'role': 'user', 'content': old_topic}],
                        assistant_proposal={'description': old_topic},
                        source_schema_snapshot={'connection': old_topic},
                        submitted_snapshot={'configuration': values}, status='submitted')
                    selection = {key: values[key] for key in ('target_entity', 'source_type')}
                    response = self.post(mode, 'configuration-reset-context',
                        {'selection': selection, 'revision': row.revision, 'confirmed': True}, row.pk)
                    self.assertEqual(response.status_code, 200, response.content)
                    row.refresh_from_db()
                    self.assertEqual(row.revision, 2)
                    self.assertEqual(row.status, 'draft')
                    self.assertEqual(row.assistant_messages, [])
                    self.assertEqual(row.assistant_proposal, {})
                    self.assertEqual(row.description, '')
                    self.assertEqual(row.source_schema_snapshot, {})
                    self.assertEqual(row.field_instructions, {})
                    self.assertEqual(row.line_field_instructions, {})
                    self.assertEqual(row.submitted_snapshot['configuration']['description'], old_topic)
                    self.assertNotIn(old_topic, json.dumps(configuration.snapshot(row)))
                    # Reloaded page uses the cleared record, not the old browser draft.
                    slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
                    page = self.client.get(f'/{slug}/configuration/{row.pk}/')
                    profile = next(item for item in page.context['finance_state']['profiles'] if item['id'] == row.pk)
                    self.assertEqual(profile['assistant_messages'], [])
                    self.assertEqual(profile['description'], '')
                    self.respond({'message': 'What would you like to configure?', 'updates': {}})
                    chat = self.post(mode, 'configuration-chat', {'configuration': configuration.snapshot(row),
                        'messages': profile['assistant_messages'], 'message': 'What information do you need?'}, row.pk)
                    self.assertEqual(chat.status_code, 200, chat.content)
                    self.assertNotIn(old_topic, json.dumps(self.provider.call_args.args[1]))

    def test_reset_requires_confirmation_scope_and_current_revision(self):
        for mode in ('ap', 'ar'):
            row = configuration.save(mode, self.complete(mode), submit=True)
            selection = {'target_entity': row.target_entity, 'source_type': row.source_type}
            body = {'selection': selection, 'revision': row.revision, 'confirmed': True}
            token = self.post(mode, 'configuration-review', {'configuration': configuration.snapshot(row), 'submit': True}, row.pk).json()['confirmation_token']
            old_values = configuration.snapshot(row)
            for changed, expected in (({'confirmed': False}, 400), ({'revision': 0}, 409),
                ({'selection': {**selection, 'source_type': 'database'}}, 400),
                ({'selection': {**selection, 'target_entity': 'unknown'}}, 400)):
                response = self.post(mode, 'configuration-reset-context', {**body, **changed}, row.pk)
                self.assertEqual(response.status_code, expected, response.content)
                row.refresh_from_db()
                self.assertEqual(configuration.snapshot(row), old_values)
            self.assertEqual(self.post(mode, 'configuration-reset-context', body, row.pk).status_code, 200)
            for action, data in (
                ('configuration-reset-context', body),
                ('configuration-chat', {'configuration': old_values, 'message': 'Continue'}),
                ('configuration-review', {'configuration': old_values, 'submit': True}),
                ('submit', {'configuration': old_values, 'confirmation_token': token, 'confirmed': True, 'messages': []}),
            ):
                self.assertEqual(self.post(mode, action, data, row.pk).status_code, 409)

    def test_reset_unsaved_draft_does_not_create_configuration_or_touch_other_chats(self):
        for mode in ('ap', 'ar'):
            existing = configuration.save(mode, self.complete(mode))
            for target in (party_key(mode), 'purchase_order', 'delivery_receipt', 'sales_invoice', 'payment'):
                for source in ('database', 'document'):
                    selection = {'target_entity': target, 'source_type': source}
                    response = self.post(mode, 'configuration-reset-context', {'selection': selection, 'confirmed': True})
                    self.assertEqual(response.status_code, 200, response.content)
                    record = response.json()['record']
                    self.assertIsNone(record['id'])
                    self.assertEqual(record['name'], '')
                    self.assertEqual(record['target_entity'], target)
                    self.assertEqual(record['source_type'], source)
                    self.assertEqual(record['assistant_messages'], [])
                    self.assertIsNone(record['database_source'])
                    self.assertIsNone(record['source_table'])
                    self.assertTrue(record['encoding_rules']['required_fields'])
            existing.refresh_from_db()
            self.assertEqual(existing.name, 'Test invoices')
            self.assertEqual(existing.revision, 1)
            self.assertEqual(model(mode, 'ExtractionConfiguration').objects.count(), 1)
        self.provider.assert_not_called()

    def test_reset_saved_database_mapping_clears_selected_source_and_only_this_configuration(self):
        source, _, table = self.database()
        for mode in ('ap', 'ar'):
            target = party_key(mode)
            other = configuration.save(mode, self.complete(mode))
            row = configuration.save(mode, {**self.values(mode), 'name': 'Big and small customers',
                'target_entity': target, 'source_type': 'database', 'database_source': source.pk,
                'source_table': table.pk, 'source_key_fields': ['id'],
                'field_mappings': {target+'_code': {'source': 'id', 'transform': 'trim'}},
                'encoding_rules': {'default_currency': 'USD', 'duplicate_policy': 'skip'}})
            response = self.post(mode, 'configuration-reset-context', {'revision': row.revision, 'confirmed': True,
                'selection': {'target_entity': target, 'source_type': 'database'}}, row.pk)
            self.assertEqual(response.status_code, 200, response.content)
            row.refresh_from_db()
            self.assertIsNone(row.database_source_id)
            self.assertIsNone(row.source_table_id)
            self.assertEqual(row.source_key_fields, [])
            self.assertEqual(row.field_mappings, {})
            self.assertEqual(row.encoding_rules['duplicate_policy'], 'review')
            self.assertEqual(row.encoding_rules['default_currency'], 'PHP')
            self.assertEqual(row.encoding_rules['line_required_fields'], [])
            other.refresh_from_db()
            self.assertEqual(other.name, 'Test invoices')
            self.assertEqual(other.revision, 1)
        self.assertTrue(DatabaseSource.objects.filter(pk=source.pk).exists())
        self.assertTrue(DatabaseTable.objects.filter(pk=table.pk).exists())
        self.provider.assert_not_called()

    def test_assistant_cannot_switch_selected_target(self):
        self.respond({'message': 'Let’s configure payments.', 'updates': {'target_entity': 'payment', 'name': 'Payments'}})
        response = self.post('ap', 'configuration-chat', {'configuration': self.values('ap'), 'message': 'I need payments'})
        self.assertEqual(response.status_code, 400, response.content)

    def test_unknown_fields_status_and_invalid_rules_are_rejected(self):
        for updates in ({'status': 'submitted'}, {'field_instructions': {'invented_field': 'guess'}},
                        {'encoding_rules': {'default_currency': 'invalid'}}, {'target_entity': 'unknown'}):
            self.respond({'message': 'Done', 'updates': updates})
            response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Configure'})
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(model('ar', 'LLMExtractionLog').objects.latest('pk').status, 'failed')
        self.assertFalse(model('ar', 'ExtractionConfiguration').objects.exists())

    def test_provider_failure_is_logged_and_does_not_save(self):
        self.provider.side_effect = RuntimeError('provider unavailable')
        response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Help'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('llm_log_no', response.json())
        self.assertFalse(model('ar', 'ExtractionConfiguration').objects.exists())

    def test_save_requires_exact_confirmed_review_in_both_modules(self):
        for mode in ('ap', 'ar'):
            data = self.complete(mode)
            body = {'configuration': data, 'submit': True, 'messages': []}
            self.assertEqual(self.post(mode, 'submit', body).status_code, 400)
            review = self.post(mode, 'configuration-review', body)
            self.assertEqual(review.status_code, 200, review.content)
            body.update(review.json())
            self.assertFalse(model(mode, 'ExtractionConfiguration').objects.exists())
            self.assertEqual(self.post(mode, 'submit', body).status_code, 400)
            body['confirmed'] = True
            body['configuration']['name'] = 'Changed after review'
            self.assertEqual(self.post(mode, 'submit', body).status_code, 400)
            body['configuration']['name'] = 'Test invoices'
            saved = self.post(mode, 'submit', body)
            self.assertEqual(saved.status_code, 200, saved.content)
            self.assertEqual(model(mode, 'ExtractionConfiguration').objects.get().status, 'submitted')

    def test_draft_confirmation_cannot_activate_or_cross_modules(self):
        body = {'configuration': self.complete(), 'submit': False, 'confirmed': True}
        body.update(self.post('ar', 'configuration-review', body).json())
        self.assertEqual(self.post('ar', 'submit', body).status_code, 400)
        self.assertEqual(self.post('ap', 'configuration', body).status_code, 400)
        saved = self.post('ar', 'configuration', body)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()['record']['status'], 'draft')

    def test_existing_configuration_and_snapshot_unchanged_by_chat(self):
        row = configuration.save('ar', self.complete(), submit=True)
        before = row.submitted_snapshot
        self.respond({'message': 'Edit the extraction instructions in the setup controls.'})
        response = self.post('ar', 'configuration-chat', {'configuration': configuration.snapshot(row), 'message': 'Change instructions'}, row.pk)
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertEqual(row.extraction_context, self.complete()['extraction_context'])
        self.assertEqual(row.submitted_snapshot, before)
        self.assertEqual(row.revision, 1)

    def test_stale_revision_rejected_on_review_chat_and_confirmation(self):
        row = configuration.save('ar', self.complete())
        values = configuration.snapshot(row)
        body = {'configuration': values, 'submit': False, 'confirmed': True}
        body.update(self.post('ar', 'configuration-review', body, row.pk).json())
        configuration.save('ar', values, row.pk)
        for action in ('configuration', 'configuration-review', 'configuration-chat'):
            response = self.post('ar', action, {**body, 'message': 'Hello'}, row.pk)
            self.assertEqual(response.status_code, 409, response.content)

    def test_preview_is_schema_checked_and_never_creates_accounting_records(self):
        for mode in ('ap', 'ar'):
            data = {**self.complete(mode), 'sample_text': 'Invoice TEST-1 total PHP 100'}
            self.respond({'record': {'invoice_reference_no': 'TEST-1', 'total_amount': '100'}, 'lines': [], 'issues': []})
            response = self.post(mode, 'configuration-preview', {'configuration': data})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['preview']['issues'])  # Missing account / date needs review.
            self.assertFalse(model(mode, 'sales_invoice').objects.exists())
            self.assertFalse(model(mode, 'ExtractionConfiguration').objects.exists())
            self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')
            self.respond({'record': {'unknown': 123}, 'lines': [], 'issues': []})
            self.assertEqual(self.post(mode, 'configuration-preview', {'configuration': data}).status_code, 400)

    def test_preview_requires_sample(self):
        self.assertEqual(self.post('ar', 'configuration-preview', {'configuration': self.complete()}).status_code, 400)
        self.provider.assert_not_called()

    def database(self):
        source = DatabaseSource.objects.create(name='ERP', host='localhost', database_name='erp', username='reader')
        run = ExtractionRun.objects.create(source=source, status='completed')
        schema = DatabaseSchema.objects.create(run=run, name='public')
        table = DatabaseTable.objects.create(schema=schema, name='invoices')
        DatabaseColumn.objects.create(table=table, name='id', ordinal_position=1, formatted_type='integer')
        return source, run, table

    def test_fabricated_columns_rejected(self):
        source, _, table = self.database()
        data = {**self.values(), 'source_type': 'database', 'database_source': source.pk, 'source_table': table.pk}
        self.respond({'message': 'Map the reference', 'updates': {'field_mappings': {'invoice_reference_no': {'source': 'invented', 'transform': 'trim'}}}})
        response = self.post('ar', 'configuration-chat', {'configuration': data, 'message': 'Suggest mapping'})
        self.assertEqual(response.status_code, 400, response.content)

    def test_confirmation_expires(self):
        body = {'configuration': self.complete(), 'submit': True, 'confirmed': True}
        with patch('django.core.signing.time.time', return_value=1):
            body.update(self.post('ar', 'configuration-review', body).json())
        self.assertEqual(self.post('ar', 'submit', body).status_code, 400)

    def test_setup_pages_load_real_context_for_both_modules(self):
        for slug, mode in [('accounts-receivable', 'ar'), ('accounts-payable', 'ap')]:
            response = self.client.get(f'/{slug}/configuration/new/?step=0')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['finance_config']['mode'], mode)
            self.assertIn('sample_documents', response.context['finance_state'])

    def test_explicit_selection_required_and_must_match_draft(self):
        body = {'configuration': self.values(), 'message': 'Help', 'selection': {}}
        self.assertEqual(self.post('ar', 'configuration-chat', body).status_code, 400)
        body['selection'] = {'target_entity': 'payment', 'source_type': 'document'}
        self.assertEqual(self.post('ar', 'configuration-chat', body).status_code, 400)
        self.provider.assert_not_called()

    def test_requirements_are_isolated_for_every_module_target_and_source(self):
        from accounts_receivable.services.catalog import TARGETS
        for mode in ('ap', 'ar'):
            for target in TARGETS[mode]:
                for source in ('document', 'database'):
                    response = self.post(mode, 'configuration-context', {'selection': {'target_entity': target, 'source_type': source}})
                    self.assertEqual(response.status_code, 200, response.content)
                    result = response.json()
                    self.assertEqual([entry['key'] for entry in result['catalog']], [target])
                    self.assertIn('source_table' if source == 'database' else 'extraction_context', result['parameters'])
                    if target in ('customer', 'supplier', 'payment'):
                        self.assertEqual(result['catalog'][0]['lineFields'], [])
                        self.assertNotIn('line_item_context', result['parameters'])
                    else:
                        self.assertTrue(result['catalog'][0]['lineFields'])
                        self.assertNotIn('line_source_table' if source == 'database' else 'line_item_context', result['parameters'])
        self.provider.assert_not_called()

    def test_assistant_cannot_switch_source_or_mix_source_settings(self):
        for updates in ({'source_type': 'database'}, {'database_source': 1}, {'field_mappings': {}}):
            self.respond({'message': 'Update', 'updates': updates})
            response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Configure'})
            self.assertEqual(response.status_code, 400, response.content)

    def test_refresh_context_preserves_saved_answers_and_chat(self):
        row = configuration.save('ar', self.complete(), submit=True)
        row.assistant_messages = [{'role': 'user', 'content': 'Remember this'}]
        row.save()
        before = configuration.snapshot(row)
        response = self.post('ar', 'configuration-context', {'configuration': before, 'selection': {'target_entity': 'sales_invoice', 'source_type': 'document'}}, row.pk)
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertEqual(configuration.snapshot(row), before)
        self.assertEqual(row.assistant_messages[0]['content'], 'Remember this')
        self.provider.assert_not_called()

    def test_document_context_cannot_refresh_database_schema(self):
        response = self.post('ar', 'configuration-context', {'configuration': self.values(), 'selection': {'target_entity': 'sales_invoice', 'source_type': 'document'}, 'inspect_schema': True})
        self.assertEqual(response.status_code, 400)

    def test_selected_database_context_can_refresh_its_schema(self):
        source, run, _ = self.database()
        values = {**self.values(), 'source_type': 'database', 'database_source': source.pk}
        with patch('accounts_receivable.services.configuration_chat.refresh_source', return_value=run) as refresh:
            response = self.post('ar', 'configuration-context', {'configuration': values, 'selection': {'target_entity': 'sales_invoice', 'source_type': 'database'}, 'inspect_schema': True})
        self.assertEqual(response.status_code, 200, response.content)
        refresh.assert_called_once_with(source.pk)

    def test_required_fields_remain_visible_when_custom_rules_are_cleared(self):
        response = self.post('ar', 'configuration-context', {'selection': {'target_entity': 'payment', 'source_type': 'document'}})
        required = {field['key'] for field in response.json()['catalog'][0]['fields'] if field['required']}
        self.assertTrue({'customer', 'payment_reference_no', 'payment_date', 'currency', 'amount_received'} <= required)
