"""Checklist checks use local configuration only, never provider requests."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from bizmatic_django.onboarding import checklist, provider_check
from router.models import RoutingDestination, RoutingRule
from accounts_receivable.models import ExtractionConfiguration


class SetupTests(TestCase):
    def setUp(self):
        self.environment = patch('bizmatic_django.onboarding.get_env', side_effect=lambda key, default='': default)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_empty_setup_has_actions_and_workspace_alert(self):
        response = self.client.get('/setup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Application setup')
        self.assertContains(response, 'Needs setup')
        for route in ['ROUTER:destination_create', 'ACCOUNTS_PAYABLE:configuration_create', 'ACCOUNTS_RECEIVABLE:configuration_create', 'DB_EXTRACTION:source_create']:
            self.assertContains(response, reverse(route))
        response = self.client.get('/router/rules/new/')
        self.assertContains(response, 'Document routing needs setup.')
        self.assertContains(response, 'page-tour-data')
        self.assertContains(response, 'Only active rules for active destinations are used.')

    def test_destination_needs_rule_and_target_specific_submitted_profile(self):
        destination = RoutingDestination.objects.create(name='Invoices', module_name='accounts_receivable', target_model='CompanySalesInvoice')
        groups = {group['key']: group for group in checklist()}
        self.assertFalse(groups['ROUTER']['steps'][-1]['ready'])
        self.assertFalse(groups['ACCOUNTS_RECEIVABLE']['steps'][-1]['ready'])
        RoutingRule.objects.create(name='Invoices', destination=destination, instructions='Match customer invoices')
        profile = ExtractionConfiguration.objects.create(name='Invoices', target_entity='sales_invoice', source_type='document', status='draft')
        self.assertFalse({g['key']: g for g in checklist()}['ACCOUNTS_RECEIVABLE']['steps'][-1]['ready'])
        profile.status = 'submitted'
        profile.submitted_snapshot = {'configuration': {'target_entity': 'sales_invoice'}}
        profile.save()
        groups = {group['key']: group for group in checklist()}
        self.assertTrue(groups['ROUTER']['steps'][-1]['ready'])
        self.assertTrue(groups['ACCOUNTS_RECEIVABLE']['steps'][-1]['ready'])
        destination.is_active = False
        destination.save()
        self.assertFalse({g['key']: g for g in checklist()}['ROUTER']['steps'][1]['ready'])

    def test_settings_detect_placeholders_and_do_not_expose_credentials(self):
        values = {'ACCOUNTS_PAYABLE_LLM_PROVIDER': 'openai', 'ACCOUNTS_PAYABLE_OPENAI_MODEL': 'ap-model', 'ACCOUNTS_PAYABLE_OPENAI_API_KEY': 'replace-with-your-key'}
        with patch('bizmatic_django.onboarding.get_env', side_effect=lambda key, default='': values.get(key, default)):
            self.assertFalse(provider_check('ACCOUNTS_PAYABLE')[0])
            values['ACCOUNTS_PAYABLE_OPENAI_API_KEY'] = 'private-test-value'
            self.assertTrue(provider_check('ACCOUNTS_PAYABLE')[0])
            response = self.client.get('/setup/')
            self.assertNotContains(response, 'private-test-value')
            values['ACCOUNTS_PAYABLE_MAX_OUTPUT_TOKENS'] = '-1'
            self.assertFalse(provider_check('ACCOUNTS_PAYABLE')[0])

    def test_help_on_each_workspace_and_setup_is_read_only(self):
        for url, title in [('/documents/', 'Documents'), ('/batches/', 'Batches'), ('/databases/', 'Database metadata'), ('/accounts-payable/configuration/', 'Extraction setup'), ('/accounts-receivable/payments/', 'Payments')]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['page_guide']['title'], title)
        self.assertEqual(self.client.post('/setup/').status_code, 405)

    def test_task_routes_have_specific_guides(self):
        from django.test import RequestFactory
        from django.urls import resolve
        from bizmatic_django.page_help import for_page

        for path, title in [('/documents/123/', 'Review a document'),
                            ('/documents/', 'Documents'),
                            ('/accounts-payable/payments/123/allocate/', 'Allocate a payment'),
                            ('/accounts-receivable/reconciliation/123/match/', 'Match document lines'),
                            ('/accounts-receivable/configuration/new/', 'Configure extraction'),
                            ('/accounts-receivable/configuration/', 'Extraction setup')]:
            request = RequestFactory().get(path)
            request.resolver_match = resolve(path)
            self.assertEqual(for_page(request)['title'], title)
        response = self.client.get('/documents/')
        self.assertContains(response, 'id="help-tour-back"')
        self.assertContains(response, 'id="help-tour-next"')
        self.assertContains(response, 'id="help-tour-close"')
        self.assertContains(response, 'Route selected')
