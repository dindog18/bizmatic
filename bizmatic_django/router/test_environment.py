"""Router environment configuration mirrors the document provider settings."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from bizmatic_django import environment
from .services import llm


class RouterEnvironmentTests(SimpleTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / '.env'
        config = patch.object(environment, 'ENV_PATH', self.path)
        config.start()
        self.addCleanup(config.stop)
        process = patch.dict(os.environ, {}, clear=True)
        process.start()
        self.addCleanup(process.stop)

    def test_provider_switch_selects_its_own_model(self):
        self.path.write_text('ROUTER_LLM_PROVIDER=ollama\nROUTER_OLLAMA_MODEL=local-routing\nROUTER_OPENAI_MODEL=cloud-routing\n')
        self.assertEqual(llm.settings().model, 'local-routing')
        os.environ['ROUTER_LLM_PROVIDER'] = 'openai'
        self.assertEqual(llm.settings().model, 'cloud-routing')
        self.assertEqual(llm.settings().provider, 'openai')

    def test_missing_provider_model_identifies_the_required_variable(self):
        self.path.write_text('ROUTER_LLM_PROVIDER=google\n')
        with self.assertRaisesMessage(ValueError, 'ROUTER_GOOGLE_MODEL is not configured.'):
            llm.settings()

    def test_process_model_override_wins_and_doc_settings_are_independent(self):
        self.path.write_text('DOC_EXTRACTION_LLM_PROVIDER=google\nDOC_EXTRACTION_GOOGLE_MODEL=document-model\nROUTER_LLM_PROVIDER=alibaba\nROUTER_ALIBABA_MODEL=router-file-model\n')
        os.environ['ROUTER_ALIBABA_MODEL'] = 'router-process-model'
        self.assertEqual(llm.settings().model, 'router-process-model')
        self.assertEqual(llm.settings().provider, 'alibaba')
        self.assertEqual(environment.get_env('DOC_EXTRACTION_GOOGLE_MODEL'), 'document-model')
