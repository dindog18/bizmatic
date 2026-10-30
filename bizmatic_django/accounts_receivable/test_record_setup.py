"""Record First uses actual metadata, the setup LLM, signed tests and confirmed saves."""
import json
import os
from copy import deepcopy
from unittest.mock import AsyncMock, patch, MagicMock

from django.test import TestCase, Client
from django.core.exceptions import ValidationError

from accounts_receivable.services import configuration
from accounts_receivable.services.catalog import model, party_key
from accounts_receivable.services.setup import context, database, documents
from db_extraction.models import DatabaseSource, ExtractionRun, DatabaseSchema, DatabaseTable, DatabaseColumn, DatabaseConstraint, ConstraintColumn
from document_extraction.models import Document, LLMExtractionLog, DocExtractionLog


class RecordSetupTests(TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CONFIG_ASSISTANT_LLM_PROVIDER': 'ollama', 'CONFIG_ASSISTANT_OLLAMA_MODEL': 'record-setup-test'})
        env.start(); self.addCleanup(env.stop)
        self.provider = AsyncMock()
        provider = patch('accounts_receivable.services.llm.invoke_with_llm', self.provider)
        provider.start(); self.addCleanup(provider.stop)

    def respond(self, result):
        if result.get('updates') == {}:
            result = {key: value for key, value in result.items() if key != 'updates'}
        self.provider.return_value = {'message': {'content': json.dumps(result)}}

    def post(self, mode, action, data, record_id=None):
        if action == 'setup-chat':
            selection = {key: data['configuration'][key] for key in ('target_entity', 'source_type')}
            history = self.post(mode, 'setup-chat-history', {'selection': selection}).json()
            data = {**data, 'selection': selection, 'chat_revision': history['chat_revision']}
        slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
        return self.client.post(f'/{slug}/api/{action}/'+(f'{record_id}/' if record_id else ''), data, content_type='application/json')

    def document(self, mode):
        party = party_key(mode)
        text = f'Code: DEMO-001\nName: Example Trading\n'
        rules = {}
        expected = {}
        output = {}
        for field in context.field_catalog(mode, party):
            value = 'DEMO-001' if field['key'] == party+'_code' else 'Example Trading' if field['key'] == party+'_name' else None
            if value:
                start = text.index(value)
                rules[field['id']] = {'method': 'extract', 'annotation': {'start': start, 'end': start+len(value), 'value': value, 'anchor': {'kind': 'label', 'label': 'Code' if 'code' in field['key'] else 'Name', 'occurrence': 1, 'lines': 1}}}
            else:
                rules[field['id']] = {'method': 'empty'}
            expected[field['id']], output[field['key']] = value, value
        values = {'name': 'Test setup', 'target_entity': party, 'source_type': 'document', 'revision': 1,
                  'encoding_rules': {'default_currency': 'PHP'},
                  'setup_data': {'version': 1, 'document': {'text': text, 'prompt': 'Extract the exact fields from this text.', 'rules': rules}}}
        return values, expected, {'record': output, 'lines': [], 'issues': []}

    def metadata(self, mode='ap'):
        party = party_key(mode)
        source = DatabaseSource.objects.create(name='Test source '+mode, host='example.test', database_name='test', username='reader')
        run = ExtractionRun.objects.create(source=source, status='completed')
        schema = DatabaseSchema.objects.create(run=run, name='public')
        table = DatabaseTable.objects.create(schema=schema, name=party+'s')
        for i, name in enumerate(['id', party+'_code', party+'_name', 'company_id']):
            DatabaseColumn.objects.create(table=table, name=name, ordinal_position=i+1, formatted_type='text')
        constraint = DatabaseConstraint.objects.create(table=table, name='supplier_pk', constraint_type='primary_key', definition='PRIMARY KEY (id)')
        ConstraintColumn.objects.create(constraint=constraint, column=table.columns.get(name='id'), position=1)
        return source, table

    def query(self, mode='ap'):
        party = party_key(mode)
        source, table = self.metadata(mode)
        query = {'database': str(source.pk), 'table': str(table.pk), 'keyMode': 'auto', 'keys': [], 'joins': [],
                 'filters': {'logic': 'all', 'children': []}, 'sorts': [], 'distinct': False,
                 'mappings': [{'id': 'header:'+key, 'include': True, 'method': 'column', 'column': 'base.'+key} for key in [party+'_code', party+'_name']]}
        values = {'name': 'Account mapping', 'target_entity': party, 'source_type': 'database', 'database_source': source.pk,
                  'setup_data': {'version': 1, 'database': query}}
        record = configuration.prepare(mode, values, incomplete=True)
        return record, query

    def test_prompt_creation_and_document_tests_persist_usage_in_both_modules(self):
        for mode in ('ap', 'ar'):
            for saved in (False, True):
                with self.subTest(mode=mode, saved=saved):
                    values, expected, output = self.document(mode)
                    record = configuration.save(mode, values) if saved else None
                    record_id = record.pk if record else None
                    self.respond({'prompt': 'Read every destination field.'})
                    self.provider.return_value.update(prompt_eval_count=31, eval_count=19)
                    generated = self.post(mode, 'setup-generate', {'configuration': values}, record_id)
                    self.assertEqual(generated.status_code, 200, generated.content)
                    log = model(mode, 'LLMExtractionLog').objects.get(pk=generated.json()['llm_log_no'])
                    self.assertEqual((log.status, log.purpose, log.source_type), ('completed', 'configuration', 'document'))
                    self.assertEqual((log.input_tokens, log.output_tokens), (31, 19))
                    self.assertEqual(log.configuration_id, record_id)
                    self.assertEqual(log.configuration_snapshot['name'], values['name'])
                    self.assertIn('annotations', json.loads(log.request_payload['messages'][-1]['content']))
                    self.assertGreaterEqual(log.processing_time_ms, 0)
                    self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')
                    self.respond(output)
                    self.provider.return_value.update(prompt_eval_count=43, eval_count=23)
                    tested = self.post(mode, 'setup-test', {'configuration': values, 'text': values['setup_data']['document']['text'], 'expected': expected}, record_id)
                    self.assertEqual(tested.status_code, 200, tested.content)
                    self.assertTrue(tested.json()['passed'], tested.content)
                    log = model(mode, 'LLMExtractionLog').objects.get(pk=tested.json()['llm_log_no'])
                    self.assertEqual((log.input_tokens, log.output_tokens), (43, 23))
                    self.assertEqual(log.configuration_id, record_id)
                    slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
                    activity = self.client.get(f'/{slug}/llm-logs/{log.pk}/')
                    exposed = next(item for item in activity.context['finance_state']['logs'] if item['llm_log_no'] == log.pk)
                    self.assertEqual((exposed['input_tokens'], exposed['output_tokens']), (43, 23))

    def test_database_assistant_persists_usage_but_query_and_import_do_not_call_llm(self):
        from accounts_receivable.services import imports
        from uuid import uuid4
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                record, _ = self.query(mode)
                party = party_key(mode)
                values = configuration.snapshot(record)
                self.respond({'message': 'Review and test the current table mappings.', 'updates': {}})
                self.provider.return_value.update(prompt_eval_count=53, eval_count=29)
                response = self.post(mode, 'setup-chat', {'configuration': values, 'message': 'Explain these database mappings.'})
                self.assertEqual(response.status_code, 200, response.content)
                log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                self.assertEqual((log.status, log.purpose, log.source_type), ('completed', 'configuration', 'database'))
                self.assertEqual((log.input_tokens, log.output_tokens), (53, 29))
                self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')
                original_count = model(mode, 'LLMExtractionLog').objects.count()
                self.provider.reset_mock()
                raw = [{'base.id': 1, 'base.'+party+'_code': 'CODE-001', 'base.'+party+'_name': 'Example Trading'}]
                with patch('accounts_receivable.services.setup.database.psycopg.connect') as connect:
                    connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.__iter__.return_value = raw
                    result = self.post(mode, 'setup-test', {'configuration': values, 'limit': 5})
                    self.assertEqual(result.status_code, 200, result.content)
                    self.assertTrue(result.json()['passed'], result.content)
                    saved = configuration.save(mode, values, submit=True)
                    imported = imports.execute(mode, saved.pk, {'request_id': str(uuid4()), 'revision': saved.revision, 'limit': 5, 'offset': 0})
                    self.assertEqual(imported.status, 'completed', imported.result)
                    self.assertEqual(len(imported.result['created']), 1)
                self.provider.assert_not_called()
                self.assertEqual(model(mode, 'LLMExtractionLog').objects.count(), original_count)

    def test_failed_setup_responses_keep_usage_and_attempt_links(self):
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                values, _, _ = self.document(mode)
                self.respond({'prompt': 'Incomplete prompt'})
                self.provider.return_value.update(done_reason='length', prompt_eval_count=61, eval_count=37)
                response = self.post(mode, 'setup-generate', {'configuration': values})
                self.assertEqual(response.status_code, 400, response.content)
                log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                self.assertEqual(log.status, 'failed')
                self.assertEqual((log.input_tokens, log.output_tokens), (61, 37))
                self.assertIn('output limit', log.error_message)
                self.assertEqual(log.response_payload, self.provider.return_value)
                record, _ = self.query(mode)
                self.respond({'message': 'Unsupported update.', 'updates': {'sql': 'SELECT * FROM anything'}})
                self.provider.return_value.update(prompt_eval_count=67, eval_count=41)
                response = self.post(mode, 'setup-chat', {'configuration': configuration.snapshot(record), 'message': 'Explain these mappings.'})
                self.assertEqual(response.status_code, 400, response.content)
                log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                self.assertEqual(log.status, 'failed')
                self.assertEqual((log.input_tokens, log.output_tokens), (67, 41))

    def test_malformed_usage_does_not_lose_a_valid_prompt_attempt(self):
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                values, _, _ = self.document(mode)
                self.respond({'prompt': 'Read every destination field.'})
                self.provider.return_value.update(usage=['invalid'], prompt_eval_count=71, eval_count=43)
                response = self.post(mode, 'setup-generate', {'configuration': values})
                self.assertEqual(response.status_code, 200, response.content)
                log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                self.assertEqual(log.status, 'completed')
                self.assertEqual((log.input_tokens, log.output_tokens), (71, 43))
                self.assertEqual(log.response_payload['usage'], ['invalid'])

    def test_non_object_provider_responses_have_failed_accessible_attempts(self):
        for mode in ('ap', 'ar'):
            for payload in (None, [], 'invalid response'):
                with self.subTest(mode=mode, payload=payload):
                    values, _, _ = self.document(mode)
                    self.provider.return_value = payload
                    response = self.post(mode, 'setup-generate', {'configuration': values})
                    self.assertEqual(response.status_code, 400, response.content)
                    log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                    self.assertEqual(log.status, 'failed')
                    self.assertEqual(log.response_payload, {'invalid_response': payload})
                    self.assertIsNone(log.input_tokens)
                    self.assertIsNone(log.output_tokens)

    def test_usage_is_saved_for_every_supported_setup_provider(self):
        content = json.dumps({'prompt': 'Read every destination field.'})
        compatible = {'choices': [{'message': {'content': content}}], 'usage': {'prompt_tokens': 79, 'completion_tokens': 47}}
        envelopes = {
            'openai': compatible, 'alibaba': compatible, 'deepseek': compatible,
            'anthropic': {'content': [{'type': 'text', 'text': content}], 'usage': {'input_tokens': 79, 'output_tokens': 47}},
            'google': {'candidates': [{'content': {'parts': [{'text': content}]}}], 'usageMetadata': {'promptTokenCount': 79, 'candidatesTokenCount': 47}},
            'ollama': {'message': {'content': content}, 'prompt_eval_count': 79, 'eval_count': 47},
        }
        for mode in ('ap', 'ar'):
            for provider, envelope in envelopes.items():
                with self.subTest(mode=mode, provider=provider), patch.dict(os.environ, {'CONFIG_ASSISTANT_LLM_PROVIDER': provider, f'CONFIG_ASSISTANT_{provider.upper()}_MODEL': 'usage-test-model'}):
                    values, _, _ = self.document(mode)
                    self.provider.return_value = envelope
                    response = self.post(mode, 'setup-generate', {'configuration': values})
                    self.assertEqual(response.status_code, 200, response.content)
                    log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                    self.assertEqual((log.provider, log.model_name), (provider, 'usage-test-model'))
                    self.assertEqual((log.input_tokens, log.output_tokens), (79, 47))
                    self.assertEqual(log.response_payload, envelope)
                    self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')

    def test_invalid_or_missing_token_counts_remain_unknown_and_zero_is_preserved(self):
        for mode in ('ap', 'ar'):
            for reported, expected in [({}, (None, None)), ({'prompt_tokens': -1, 'completion_tokens': True}, (None, None)), ({'prompt_tokens': '12', 'completion_tokens': 1.5}, (None, None)), ({'prompt_tokens': 0, 'completion_tokens': 0}, (0, 0))]:
                with self.subTest(mode=mode, reported=reported):
                    values, _, _ = self.document(mode)
                    self.respond({'prompt': 'Read every destination field.'})
                    self.provider.return_value['usage'] = reported
                    response = self.post(mode, 'setup-generate', {'configuration': values})
                    self.assertEqual(response.status_code, 200, response.content)
                    log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                    self.assertEqual(log.status, 'completed')
                    self.assertEqual((log.input_tokens, log.output_tokens), expected)
                    self.assertEqual(log.response_payload['usage'], reported)

    def test_provider_timeouts_leave_failed_logs_in_both_modules(self):
        self.provider.side_effect = TimeoutError('Private provider details')
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                values, _, _ = self.document(mode)
                response = self.post(mode, 'setup-generate', {'configuration': values})
                self.assertEqual(response.status_code, 400, response.content)
                log = model(mode, 'LLMExtractionLog').objects.get(pk=response.json()['llm_log_no'])
                self.assertEqual(log.status, 'failed')
                self.assertIsNone(log.input_tokens)
                self.assertIsNone(log.output_tokens)
                self.assertTrue(log.request_payload)
                self.assertNotIn('Private provider details', log.error_message)

    def test_annotation_generation_and_tests_always_use_config_assistant(self):
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                values, expected, output = self.document(mode)
                self.respond({'prompt': 'A generated prompt for every destination field.'})
                response = self.post(mode, 'setup-generate', {'configuration': values})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')
                self.assertEqual(response.json()['prompt'], 'A generated prompt for every destination field.')
                self.respond(output)
                response = self.post(mode, 'setup-test', {'configuration': values, 'text': values['setup_data']['document']['text'], 'expected': expected})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(response.json()['passed'], response.json())
                self.assertTrue(response.json()['test_token'])
                request = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
                self.assertNotIn('expected', request)
                self.assertEqual(model(mode, 'ExtractionConfiguration').objects.count(), 0)

    def test_confirmed_save_requires_current_test_and_keeps_annotations(self):
        for mode in ('ap', 'ar'):
            values, expected, output = self.document(mode)
            body = {'configuration': values, 'submit': True}
            self.assertEqual(self.post(mode, 'setup-review', body).status_code, 400)
            self.respond(output)
            result = self.post(mode, 'setup-test', {**body, 'text': values['setup_data']['document']['text'], 'expected': expected}).json()
            body['test_token'] = result['test_token']
            reviewed = self.post(mode, 'setup-review', body)
            self.assertEqual(reviewed.status_code, 200, reviewed.content)
            body['confirmation_token'] = reviewed.json()['confirmation_token']
            self.assertEqual(self.post(mode, 'setup-save', body).status_code, 400)
            saved = self.post(mode, 'setup-save', {**body, 'confirmed': True})
            self.assertEqual(saved.status_code, 200, saved.content)
            row = model(mode, 'ExtractionConfiguration').objects.get()
            self.assertEqual(row.status, 'submitted')
            self.assertEqual(row.setup_data['document']['rules'], values['setup_data']['document']['rules'])
            self.assertEqual(row.submitted_snapshot['configuration']['setup_data'], row.setup_data)
            changed = deepcopy(body); changed['configuration']['name'] = 'Changed after test'
            self.assertEqual(self.post(mode, 'setup-review', changed).status_code, 400)

    def test_completed_tests_with_issues_receive_review_receipts(self):
        values, expected, output = self.document('ap')
        for change in ('missing', 'different', 'unverified'):
            current = deepcopy(output)
            current['record']['supplier_code'] = None if change == 'missing' else 'OTHER' if change == 'different' else 'DEMO-001'
            self.respond(current)
            response = self.post('ap', 'setup-test', {'configuration': values, 'text': 'Code: DEMO-001\nName: Example Trading', 'expected': {} if change == 'unverified' else expected})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(response.json()['passed'])
            self.assertTrue(response.json()['test_token'])

    def test_document_issues_can_be_reviewed_and_saved_in_both_modules(self):
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                values, expected, output = self.document(mode)
                output['record'][party_key(mode)+'_code'] = None
                self.respond(output)
                tested = self.post(mode, 'setup-test', {'configuration': values,
                    'text': values['setup_data']['document']['text'], 'expected': expected})
                self.assertEqual(tested.status_code, 200, tested.content)
                result = tested.json()
                self.assertFalse(result['passed'])
                body = {'configuration': values, 'submit': True, 'test_token': result['test_token']}
                reviewed = self.post(mode, 'setup-review', body)
                self.assertEqual(reviewed.status_code, 200, reviewed.content)
                self.assertEqual(reviewed.json()['test_issues'], result['issues'])
                body['confirmation_token'] = reviewed.json()['confirmation_token']
                self.assertEqual(self.post(mode, 'setup-save', body).status_code, 400)
                saved = self.post(mode, 'setup-save', {**body, 'confirmed': True})
                self.assertEqual(saved.status_code, 200, saved.content)
                self.assertEqual(saved.json()['record']['status'], 'submitted')
                self.assertEqual(model(mode, party_key(mode).title()).objects.count(), 0)
                changed = deepcopy(body)
                changed['configuration']['setup_data']['document']['prompt'] += ' Changed'
                self.assertEqual(self.post(mode, 'setup-review', changed).status_code, 400)

    def test_source_text_edits_require_new_annotation_offsets(self):
        values, _, _ = self.document('ar')
        values['setup_data']['document']['text'] = 'Changed source text'
        response = self.post('ar', 'setup-generate', {'configuration': values})
        self.assertEqual(response.status_code, 400)
        self.provider.assert_not_called()

    def test_draft_save_is_confirmed_but_does_not_require_activation_test(self):
        values, _, _ = self.document('ap')
        body = {'configuration': values, 'submit': False}
        reviewed = self.post('ap', 'setup-review', body)
        self.assertEqual(reviewed.status_code, 200)
        response = self.post('ap', 'setup-save', {**body, 'confirmed': True, 'confirmation_token': reviewed.json()['confirmation_token']})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(model('ap', 'ExtractionConfiguration').objects.get().status, 'draft')

    def test_read_only_sql_uses_metadata_identifiers_and_bound_filter_values(self):
        record, query = self.query()
        attack = "x' OR 1=1; DROP TABLE suppliers; --"
        query['filters']['children'] = [{'column': 'base.supplier_name', 'operator': 'contains', 'value': attack}]
        metadata = database.validate_query('ap', record, query, complete=True)
        statement, params, _ = database.compile_query(query, metadata)
        self.assertNotIn(attack, statement.as_string())
        self.assertIn(attack, params[0])
        self.assertIn('"public"."suppliers"', statement.as_string())
        self.assertEqual(params[-1], 5001)
        connection = MagicMock(); connection.execute.return_value.fetchall.return_value = []
        with patch('accounts_receivable.services.setup.database.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value = connection
            database.fetch(query, metadata)
        self.assertEqual(connection.execute.call_args_list[0].args[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')

    def test_unknown_columns_and_cross_source_tables_are_rejected(self):
        record, query = self.query()
        query['mappings'][0]['column'] = 'base.not_a_column'
        with self.assertRaises(ValidationError):
            database.validate_query('ap', record, query, complete=True)
        query['mappings'][0]['column'] = 'base.supplier_code'
        other_source = DatabaseSource.objects.create(name='Other', host='other', database_name='other', username='reader')
        run = ExtractionRun.objects.create(source=other_source, status='completed')
        schema = DatabaseSchema.objects.create(run=run, name='public')
        other = DatabaseTable.objects.create(schema=schema, name='other')
        query['joins'] = [{'id': 'other', 'table': str(other.pk), 'type': 'left', 'on': []}]
        with self.assertRaises(ValidationError):
            database.validate_query('ap', record, query)

    def test_query_test_and_runtime_import_share_the_same_mapping_plan(self):
        record, query = self.query()
        raw = [{'base.id': 1, 'base.supplier_code': 'S1', 'base.supplier_name': 'One'}]
        with patch('accounts_receivable.services.setup.database.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.__iter__.return_value = raw
            result = database.test('ap', record, 5)
            self.assertTrue(result['passed'], result)
            header, lines = database.import_rows('ap', record, 5, 0)[0]
        self.assertEqual(header['header:supplier_code'], 'S1')
        self.assertEqual(header['id'], 1)
        self.assertEqual(lines, [])

    def test_distinct_line_identifiers_preserve_identical_item_values(self):
        record, query = self.query()
        query['mappings'].append({'id': 'line:description', 'include': True, 'method': 'column', 'column': 'item.description'})
        raw = [{'base.id': 1, 'base.supplier_code': 'S1', 'base.supplier_name': 'One', 'item.id': n, 'item.description': 'Same item'} for n in (1, 2, 2)]
        records, issues, _ = database.grouped('ap', record, query, raw, ['item.id'])
        self.assertEqual(len(records[0]['lines']), 2)
        self.assertFalse(issues)

    def test_existing_llm_extractions_appear_in_the_document_picker(self):
        document = Document.objects.create(file_name='provided.jpg', document_type='image', storage_path='sample.jpg')
        failed = LLMExtractionLog.objects.create(fk_document_no=document, status='failed', markdown_text='Invalid')
        row = LLMExtractionLog.objects.create(fk_document_no=document, status='completed', markdown_text='Usable text')
        choices = context.documents()
        self.assertEqual(choices[0]['id'], f'llm:{row.pk}')
        self.assertEqual(context.document_text(choices[0]['id'])['text'], 'Usable text')
        with self.assertRaises(ValidationError):
            context.document_text(f'llm:{failed.pk}')

    def test_new_query_plan_imports_through_the_existing_idempotent_runtime(self):
        from uuid import uuid4
        from accounts_receivable.services import imports
        record, query = self.query()
        saved = configuration.save('ap', configuration.snapshot(record), submit=True)
        raw = [{'base.id': 1, 'base.supplier_code': 'S1', 'base.supplier_name': 'One'}]
        with patch('accounts_receivable.services.setup.database.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.__iter__.return_value = raw
            request = {'request_id': str(uuid4()), 'revision': saved.revision, 'limit': 5, 'offset': 0}
            run = imports.execute('ap', saved.pk, request)
            self.assertEqual(run.status, 'completed', run.result)
            self.assertEqual(len(run.result['created']), 1)
            self.assertEqual(imports.execute('ap', saved.pk, request).pk, run.pk)
        self.assertEqual(model('ap', 'supplier').objects.count(), 1)

    def test_generated_document_profiles_remain_usable_by_record_extraction(self):
        from accounts_receivable.services.extraction import save_result
        for mode in ('ap', 'ar'):
            values, _, output = self.document(mode)
            saved = configuration.save(mode, values, submit=True)
            record = save_result(mode, saved, output)
            self.assertEqual(getattr(record, party_key(mode)+'_code'), 'DEMO-001')

    def test_unicode_annotation_offsets_follow_browser_utf16_positions(self):
        values, _, _ = self.document('ap')
        document = values['setup_data']['document']
        document['text'] = '😀\n'+document['text']
        for rule in document['rules'].values():
            if rule['method'] == 'extract':
                rule['annotation']['start'] += 3
                rule['annotation']['end'] += 3
        self.respond({'prompt': 'Keep the Unicode document values.'})
        response = self.post('ap', 'setup-generate', {'configuration': values})
        self.assertEqual(response.status_code, 200, response.content)

    def test_source_date_formats_compare_with_canonical_model_dates(self):
        from accounts_receivable.services.setup.documents import expected_value
        values, _, _ = self.document('ar')
        record = configuration.prepare('ar', values, incomplete=True)
        record.encoding_rules['date_format'] = 'MM/DD/YYYY'
        field = model('ar', 'sales_invoice')._meta.get_field('invoice_date')
        self.assertEqual(expected_value(field, '02/28/2026', record), expected_value(field, '2026-02-28', record, canonical=True))

    def test_test_request_omits_annotation_example_values(self):
        values, expected, output = self.document('ar')
        self.respond(output)
        response = self.post('ar', 'setup-test', {'configuration': values, 'text': values['setup_data']['document']['text'], 'expected': expected})
        self.assertEqual(response.status_code, 200, response.content)
        request = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
        for rule in request['configuration']['field_rules'].values():
            self.assertNotIn('annotation', rule)
            self.assertNotIn('example', rule)

    def test_chat_rejects_mapping_patch_without_changing_inputs(self):
        record, query = self.query()
        self.respond({'message': 'Use the supplier code as requested. Review and test the updated mapping.',
                      'updates': {'database': {'mappings': [{'id': 'header:supplier_code', 'transform': 'trim'}]}}})
        response = self.post('ap', 'setup-chat', {'configuration': configuration.snapshot(record), 'message': 'Trim the supplier code.'})
        self.assertEqual(response.status_code, 400, response.content)
        mappings = {item['id']: item for item in record.setup_data['database']['mappings']}
        self.assertEqual(mappings['header:supplier_code'].get('transform', 'identity'), 'identity')
        self.assertEqual(mappings['header:supplier_code']['column'], 'base.supplier_code')
        self.assertEqual(mappings['header:supplier_name']['column'], 'base.supplier_name')
        self.assertEqual(self.provider.call_args.kwargs['config_prefix'], 'CONFIG_ASSISTANT')

    def test_expected_answers_cannot_override_empty_or_constant_rules(self):
        for method in ('empty', 'constant'):
            values, expected, output = self.document('ap')
            values['setup_data']['document']['rules']['header:phone'] = {'method': method, 'value': '555-0100'}
            output['record']['phone'] = '555-0199'
            expected['header:phone'] = '555-0199'
            self.respond(output)
            response = self.post('ap', 'setup-test', {'configuration': values, 'text': values['setup_data']['document']['text'], 'expected': expected})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(response.json()['passed'])
            self.assertTrue(response.json()['test_token'])

    def test_old_save_endpoints_cannot_bypass_record_first_test_receipts(self):
        for mode in ('ap', 'ar'):
            values, _, _ = self.document(mode)
            body = {'configuration': values, 'submit': True, 'confirmed': True}
            self.assertEqual(self.post(mode, 'configuration-review', body).status_code, 400)
            self.assertEqual(self.post(mode, 'submit', body).status_code, 400)
            saved = configuration.save(mode, values)
            stripped = configuration.snapshot(saved)
            stripped.pop('setup_data')
            self.assertEqual(self.post(mode, 'configuration', {'configuration': stripped, 'confirmed': True}, saved.pk).status_code, 400)
            saved.refresh_from_db()
            self.assertEqual(saved.setup_data['version'], 1)

    def test_saved_context_reset_retains_record_first_validation(self):
        for mode in ('ap', 'ar'):
            values, _, _ = self.document(mode)
            saved = configuration.save(mode, values)
            response = self.post(mode, 'configuration-reset-context', {
                'selection': {'target_entity': party_key(mode), 'source_type': 'document'},
                'revision': saved.revision, 'confirmed': True}, saved.pk)
            self.assertEqual(response.status_code, 200, response.content)
            saved.refresh_from_db()
            self.assertEqual(saved.setup_data, {'version': 1, 'document': {'text': '', 'prompt': '', 'rules': {}}})
            self.assertEqual(saved.status, 'draft')
            self.assertEqual(saved.assistant_messages, [])

    def test_old_record_first_bookmarks_redirect_to_production(self):
        response = self.client.get('/configuration-lab/record-preview/?module=ar&record=customer&source=database')
        self.assertRedirects(response, '/accounts-receivable/configuration/new/?target=customer&source=database')
        self.assertEqual(self.client.get('/configuration-lab/conversation/').status_code, 404)

    def test_primary_setup_routes_and_csrf(self):
        for mode, slug in [('ap', 'accounts-payable'), ('ar', 'accounts-receivable')]:
            response = self.client.get(f'/{slug}/configuration/new/?fresh=1')
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'accounting/setup.html')
            response = self.post(mode, 'setup-context', {})
            self.assertEqual(len(response.json()['catalog']), 5)
            self.assertTrue(any(item['lineFields'] for item in response.json()['catalog']))
            response = Client(enforce_csrf_checks=True).post(f'/{slug}/api/setup-test/', {}, content_type='application/json')
            self.assertEqual(response.status_code, 403)
