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
        self.provider.return_value = {'message': {'content': json.dumps(result)}}

    def post(self, mode, action, body, record_id=None):
        if action == 'configuration-chat' and 'selection' not in body:
            body = {**body, 'selection': {key: body['configuration'][key] for key in ('target_entity', 'source_type')}}
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

    def test_both_modules_can_chat_from_blank_without_saving(self):
        for mode in ('ap', 'ar'):
            self.respond({'message': 'What date format do you use?', 'updates': {'name': 'Invoice setup', 'document_type': 'Invoice'}})
            response = self.post(mode, 'configuration-chat', {'configuration': self.values(mode), 'message': 'Help with invoices'})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()['record']['name'], 'Invoice setup')
            self.assertIsNone(response.json()['record']['id'])
            self.assertEqual(len(response.json()['record']['assistant_messages']), 2)
            self.assertFalse(model(mode, 'ExtractionConfiguration').objects.exists())
            log = model(mode, 'LLMExtractionLog').objects.get()
            self.assertIsNone(log.configuration_id)
            self.assertEqual(log.status, 'completed')
            self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')
            context = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
            self.assertTrue(context['catalog'][0]['fields'])

    def test_question_only_and_follow_up_preserve_configuration(self):
        data = self.complete()
        self.respond({'message': 'Dates are normalized to ISO format.', 'updates': {}})
        response = self.post('ar', 'configuration-chat', {'configuration': data, 'message': 'Explain dates',
            'messages': [{'role': 'user', 'content': 'Use PHP'}, {'role': 'assistant', 'content': 'PHP selected.'}]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['record']['extraction_context'], data['extraction_context'])
        self.assertEqual(len(response.json()['record']['assistant_messages']), 4)

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
        self.respond({'message': 'Updated working instructions.', 'updates': {'extraction_context': 'New instructions'}})
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

    def test_schema_and_readonly_sample_tool_are_grounded(self):
        source, _, table = self.database()
        data = {**self.values(), 'source_type': 'database', 'database_source': source.pk, 'source_table': table.pk, 'source_key_fields': ['id']}
        self.provider.side_effect = [
            {'message': {'content': json.dumps({'message': 'Read a sample', 'tool': {'name': 'sample_rows'}})}},
            {'message': {'content': json.dumps({'message': 'The key is id.', 'updates': {}})}}]
        with patch('accounts_receivable.services.imports.read_rows', return_value=[({'id': 7}, [])]) as read:
            response = self.post('ar', 'configuration-chat', {'configuration': data, 'message': 'Inspect one row'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(read.call_args.args[1:], (1, 0))
        context = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(context['tables'][0]['column_definitions'][0]['formatted_type'], 'integer')
        self.assertEqual(context['tool_result']['sample_rows'][0][0], {'id': 7})
        self.assertNotIn('password', json.dumps(context))

    def test_schema_refresh_tool_uses_existing_connection(self):
        source, run, _ = self.database()
        self.provider.side_effect = [
            {'message': {'content': json.dumps({'message': 'Inspect schema', 'tool': {'name': 'inspect_schema', 'source_id': source.pk}})}},
            {'message': {'content': json.dumps({'message': 'Schema loaded', 'updates': {}})}}]
        with patch('accounts_receivable.services.configuration_chat.refresh_source', return_value=run) as refresh:
            response = self.post('ar', 'configuration-chat', {'configuration': {**self.values(), 'source_type': 'database'}, 'message': 'Refresh ERP schema'})
        self.assertEqual(response.status_code, 200, response.content)
        refresh.assert_called_once_with(source.pk)

    def test_fabricated_columns_rejected(self):
        source, _, table = self.database()
        data = {**self.values(), 'source_type': 'database', 'database_source': source.pk, 'source_table': table.pk}
        self.respond({'message': 'Map the reference', 'updates': {'field_mappings': {'invoice_reference_no': {'source': 'invented', 'transform': 'trim'}}}})
        response = self.post('ar', 'configuration-chat', {'configuration': data, 'message': 'Suggest mapping'})
        self.assertEqual(response.status_code, 400, response.content)

    def test_confirmed_supplier_mapping_shorthand_succeeds_without_repair(self):
        source, _, table = self.database()
        table.name = 'VANS_suppliermanagement'
        table.save()
        mappings = {'supplier_code': 'supplier_code', 'supplier_name': 'supplier_company_name',
                    'contact_person': 'contact_person', 'phone': 'contact_number', 'payment_terms_days': 'terms'}
        for index, name in enumerate(mappings.values(), start=2):
            DatabaseColumn.objects.create(table=table, name=name, ordinal_position=index, formatted_type='text')
        values = {**self.values('ap'), 'name': 'Supplier setup', 'target_entity': 'supplier', 'source_type': 'database'}
        updates = {'database_source': source.pk, 'source_table': table.pk,
                   'source_key_fields': ['supplier_code'], 'field_mappings': mappings}
        self.provider.return_value = {'choices': [{'message': {'content': json.dumps({
            'message': 'Supplier mappings added. Please review the guide before saving.', 'updates': updates})},
            'finish_reason': 'stop'}]}
        with patch.dict(os.environ, {'CONFIG_ASSISTANT_LLM_PROVIDER': 'alibaba', 'CONFIG_ASSISTANT_ALIBABA_MODEL': 'setup-test'}):
            response = self.post('ap', 'configuration-chat', {'configuration': values, 'message':
                'Yes use public.VANS_suppliermanagement. Identification should be supplier_code. '
                'Mappings: supplier_code -> supplier_code, supplier_name -> supplier_company_name, '
                'contact_person -> contact_person, phone -> contact_number, payment_terms_days -> terms.'})
        self.assertEqual(response.status_code, 200, response.content)
        record = response.json()['record']
        self.assertEqual(record['source_table'], table.pk)
        self.assertEqual(record['source_key_fields'], ['supplier_code'])
        self.assertEqual(record['field_mappings'], {key: {'source': value, 'transform': 'identity'} for key, value in mappings.items()})
        self.assertEqual(self.provider.call_count, 1)
        self.assertFalse(model('ap', 'ExtractionConfiguration').objects.exists())
        system = self.provider.call_args.args[1]['messages'][0]['content']
        self.assertIn('response schema', system)
        self.assertIn('"supplier_name":{"type":"object"', system)

    def test_shorthand_still_rejects_invented_columns_with_specific_repair_guidance(self):
        source, _, table = self.database()
        data = {**self.values(), 'source_type': 'database', 'database_source': source.pk, 'source_table': table.pk}
        self.respond({'message': 'Map the reference', 'updates': {'field_mappings': {'invoice_reference_no': 'invented'}}})
        response = self.post('ar', 'configuration-chat', {'configuration': data, 'message': 'Suggest mapping'})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('field_mappings.invoice_reference_no.source must be a column', response.json()['message'])
        self.assertEqual(self.provider.call_count, 2)

    def test_compatible_provider_repair_receives_mapping_contract(self):
        self.provider.side_effect = [
            {'choices': [{'message': {'content': '{"message":"Missing updates"}'}}]},
            {'choices': [{'message': {'content': '{"message":"What else is needed?","updates":{}}'}}]},
        ]
        with patch.dict(os.environ, {'CONFIG_ASSISTANT_LLM_PROVIDER': 'alibaba', 'CONFIG_ASSISTANT_ALIBABA_MODEL': 'setup-test'}):
            response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Help'})
        self.assertEqual(response.status_code, 200, response.content)
        for call in self.provider.call_args_list:
            self.assertIn('response schema', call.args[1]['messages'][0]['content'])

    def test_missing_update_envelope_gets_one_repair(self):
        self.provider.side_effect = [
            {'message': {'content': json.dumps({'message': 'I understand the invoice setup.'})}},
            {'message': {'content': json.dumps({'message': 'Name added to the guide.', 'updates': {'name': 'Invoices'}})}}]
        response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Name it Invoices'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['record']['name'], 'Invoices')
        self.assertEqual(self.provider.call_count, 2)
        self.assertEqual(model('ar', 'LLMExtractionLog').objects.filter(status='failed').count(), 1)

    def test_unknown_tool_source_is_explained_without_crashing(self):
        self.provider.side_effect = [
            {'message': {'content': json.dumps({'message': 'Inspect', 'tool': {'name': 'inspect_schema', 'source_id': 999}})}},
            {'message': {'content': json.dumps({'message': 'Please choose an available source.', 'updates': {}})}}]
        response = self.post('ar', 'configuration-chat', {'configuration': {**self.values(), 'source_type': 'database'}, 'message': 'Read the schema'})
        self.assertEqual(response.status_code, 200, response.content)
        context = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
        self.assertIn('error', context['tool_result'])

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

    def test_claiming_changes_without_updates_triggers_repair(self):
        self.provider.side_effect = [
            {'message': {'content': json.dumps({'message': "I've captured the name.", 'updates': {}})}},
            {'message': {'content': json.dumps({'message': 'The working name is Invoices.', 'updates': {'name': 'Invoices'}})}}]
        response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Name it Invoices'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['record']['name'], 'Invoices')

    def test_nested_answers_preserve_existing_rules_and_ollama_schema(self):
        self.respond({'message': 'Date format updated.', 'updates': {'encoding_rules': {'date_format': 'DD/MM/YYYY'}}})
        response = self.post('ar', 'configuration-chat', {'configuration': self.values(), 'message': 'Use DD/MM/YYYY'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['record']['encoding_rules']['default_currency'], 'PHP')
        self.assertEqual(response.json()['record']['encoding_rules']['date_format'], 'DD/MM/YYYY')
        body = self.provider.call_args.args[1]
        self.assertEqual(body['format']['required'], ['updates', 'message'])
        self.assertFalse(body['format']['properties']['updates']['additionalProperties'])

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

    def test_selected_chat_receives_only_its_catalog_and_source_fields(self):
        self.respond({'message': 'What labels identify your customers?', 'updates': {}})
        values = {**self.values(), 'target_entity': 'customer'}
        response = self.post('ar', 'configuration-chat', {'configuration': values, 'message': 'What is needed?'})
        self.assertEqual(response.status_code, 200, response.content)
        body = self.provider.call_args.args[1]
        context = json.loads(body['messages'][1]['content'])
        self.assertEqual([entry['key'] for entry in context['catalog']], ['customer'])
        self.assertEqual(context['selection'], {'target_entity': 'customer', 'source_type': 'document'})
        self.assertNotIn('database_source', context['editable_fields'])
        properties = body['format']['properties']['updates']['properties']
        self.assertNotIn('source_type', properties)
        self.assertNotIn('invoice_reference_no', properties['field_instructions']['properties'])
        self.assertIn('customer_code', properties['field_instructions']['properties'])

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

    def test_response_schema_required_arrays_do_not_share_header_items(self):
        from accounts_receivable.services.configuration_chat import response_schema
        properties = response_schema('ar', 'customer', 'database')['properties']['updates']['properties']
        self.assertIn('customer_code', properties['encoding_rules']['properties']['required_fields']['items']['enum'])
        self.assertEqual(properties['encoding_rules']['properties']['line_required_fields']['maxItems'], 0)
        self.assertEqual(properties['source_key_fields']['items'], {'type': 'string'})
