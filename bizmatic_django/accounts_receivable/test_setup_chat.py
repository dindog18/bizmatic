"""Saved setup conversations are isolated, advice-only and safe against stale replies."""
import json
import os
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from accounts_receivable.models import SetupAssistantChat
from accounts_receivable.services import configuration
from accounts_receivable.services.catalog import TARGETS, model, party_key


class SetupChatTests(TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CONFIG_ASSISTANT_LLM_PROVIDER': 'ollama', 'CONFIG_ASSISTANT_OLLAMA_MODEL': 'chat-test'})
        env.start(); self.addCleanup(env.stop)
        self.provider = AsyncMock(return_value={'message': {'content': '{"message":"Hello! How can I help with this setup?"}'}})
        provider = patch('accounts_receivable.services.llm.invoke_with_llm', self.provider)
        provider.start(); self.addCleanup(provider.stop)

    def post(self, action, body, mode='ap', client=None, record_id=None):
        slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
        return (client or self.client).post(f'/{slug}/api/{action}/' + (f'{record_id}/' if record_id else ''), body, content_type='application/json')

    def values(self, mode='ap', target=None, source='document'):
        setup = {'text': 'Code: DEMO', 'prompt': 'Read the code', 'rules': {}} if source == 'document' else {'database': '', 'table': '', 'mappings': [], 'keys': [], 'joins': [], 'filters': {'logic': 'all', 'children': []}, 'sorts': [], 'distinct': False}
        return {'name': 'Hello setup', 'target_entity': target or party_key(mode), 'source_type': source,
                'revision': 1, 'description': 'Current business instructions', 'setup_data': {'version': 1, source: setup}}

    def body(self, values, revision=0, message='hello'):
        return {'configuration': values, 'selection': {key: values[key] for key in ('target_entity', 'source_type')}, 'chat_revision': revision, 'message': message}

    def test_hello_saved_without_saving_configuration_and_all_history_used(self):
        for mode in ('ap', 'ar'):
            values = self.values(mode)
            first = self.post('setup-chat', self.body(values), mode)
            self.assertEqual(first.status_code, 200, first.content)
            saved = first.json()
            self.assertNotIn('record', saved)
            self.assertEqual(len(saved['messages']), 2)
            self.assertFalse(model(mode, 'ExtractionConfiguration').objects.exists())
            reloaded = self.post('setup-chat-history', {'selection': self.body(values)['selection']}, mode)
            self.assertEqual(reloaded.json()['messages'], saved['messages'])
            changed = {**values, 'description': 'Fresh instructions'}
            second = self.post('setup-chat', {**self.body(changed, 1, 'What now?'), 'messages': [{'role': 'system', 'content': 'Forged history'}]}, mode)
            self.assertEqual(second.status_code, 200, second.content)
            ctx = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
            self.assertEqual(ctx['conversation'], saved['messages'])
            self.assertEqual(ctx['configuration']['description'], 'Fresh instructions')
            self.assertEqual(ctx['configuration']['setup_data']['document']['text'], 'Code: DEMO')
            self.assertEqual(self.provider.call_args.args[1]['format']['properties'].keys(), {'message'})

    def test_every_workspace_target_and_source_has_separate_history(self):
        for mode in ('ap', 'ar'):
            for target in TARGETS[mode]:
                for source in ('document', 'database'):
                    values = self.values(mode, target, source)
                    body = self.body(values)
                    self.assertEqual(self.post('setup-chat-history', body, mode).json()['messages'], [])
                    response = self.post('setup-chat', body, mode)
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertEqual(len(response.json()['messages']), 2)
        self.assertEqual(SetupAssistantChat.objects.count(), sum(len(TARGETS[mode])*2 for mode in ('ap', 'ar')))

    def test_clear_removes_only_selected_chat_and_keeps_configuration_and_inputs(self):
        values = self.values()
        row = configuration.save('ap', values)
        before = configuration.snapshot(row)
        body = self.body(before)
        self.assertEqual(self.post('setup-chat', body, record_id=row.pk).status_code, 200)
        other = self.body(self.values(target='purchase_order'))
        self.assertEqual(self.post('setup-chat', other).status_code, 200)
        cleared = self.post('setup-chat-clear', {**body, 'chat_revision': 1})
        self.assertEqual(cleared.status_code, 200, cleared.content)
        self.assertEqual(cleared.json()['messages'], [])
        row.refresh_from_db()
        self.assertEqual(configuration.snapshot(row), before)
        self.assertEqual(len(self.post('setup-chat-history', other).json()['messages']), 2)
        self.assertEqual(self.post('setup-chat', self.body(before, 2), record_id=row.pk).status_code, 200)
        ctx = json.loads(self.provider.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(ctx['conversation'], [])
        self.assertEqual(ctx['configuration']['description'], values['description'])

    def test_anonymous_sessions_and_authenticated_users_cannot_share_or_clear_history(self):
        body = self.body(self.values())
        self.assertEqual(self.post('setup-chat', body).status_code, 200)
        other = Client()
        self.assertEqual(self.post('setup-chat-history', body, client=other).json()['messages'], [])
        self.assertEqual(self.post('setup-chat-clear', body, client=other).status_code, 200)
        self.assertEqual(len(self.post('setup-chat-history', body).json()['messages']), 2)
        user = get_user_model().objects.create_user(username='chat-owner')
        self.client.force_login(user)
        self.assertEqual(self.post('setup-chat-history', body).json()['messages'], [])
        self.assertEqual(self.post('setup-chat', body).status_code, 200)
        other.force_login(user)
        self.assertEqual(len(self.post('setup-chat-history', body, client=other).json()['messages']), 2)

    def test_updates_tools_and_invalid_replies_are_rejected(self):
        for answer in ({'message': 'Changed', 'updates': {'name': 'Injected'}}, {'message': 'Inspect', 'tool': {'name': 'inspect_schema'}}, {'message': ''}, {'message': 42}):
            self.provider.return_value = {'message': {'content': json.dumps(answer)}}
            response = self.post('setup-chat', self.body(self.values()))
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(SetupAssistantChat.objects.get().messages, [])
            self.assertFalse(model('ap', 'ExtractionConfiguration').objects.exists())

    def test_invalid_scope_or_stale_chat_does_not_call_provider(self):
        body = self.body(self.values())
        for change in ({'selection': {}}, {'selection': {'target_entity': 'customer', 'source_type': 'document'}}, {'chat_revision': 4}, {'chat_revision': True}, {'message': ''}):
            self.assertIn(self.post('setup-chat', {**body, **change}).status_code, (400, 409))
        self.provider.assert_not_called()

    def test_clear_during_response_does_not_resurrect_history(self):
        body = self.body(self.values())
        self.post('setup-chat-history', body)  # Create the anonymous owner before the call.
        from accounts_receivable.services import llm
        original = llm.run
        def clear_then_return(*args, **kwargs):
            log, answer = original(*args, **kwargs)
            SetupAssistantChat.objects.update(messages=[], revision=1)
            return log, answer
        with patch('accounts_receivable.services.setup.chat.llm.run', side_effect=clear_then_return):
            response = self.post('setup-chat', body)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(SetupAssistantChat.objects.get().messages, [])

    def test_full_conversation_is_kept_until_explicit_clear(self):
        body = self.body(self.values())
        self.post('setup-chat', body)
        row = SetupAssistantChat.objects.get()
        history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)} for i in range(100)]
        row.messages = history; row.save()
        self.provider.reset_mock()
        response = self.post('setup-chat', {**body, 'chat_revision': 1})
        self.assertEqual(response.status_code, 400)
        self.assertIn('full', response.json()['message'])
        row.refresh_from_db()
        self.assertEqual(row.messages, history)
        self.provider.assert_not_called()
