from unittest.mock import AsyncMock, patch
import json
import os

from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import tests as fixtures
from .tests import PAYLOAD, PROFILES
from .models import EncoderChatMessage, EncoderExecution, EncoderReset
from .services import chat, execution, mapping
from .services.reset import reset


@override_settings(ENCODER_LOCAL_ENABLED=True, ENCODER_STDIO_SERVERS=PROFILES, ALLOWED_HOSTS=["localhost", "testserver"])
class ResetTests(TestCase):
    setUp = fixtures.EncoderTests.setUp
    ready = fixtures.EncoderTests.ready
    mock_connector = fixtures.EncoderTests.mock_connector

    def test_reset_preserves_snapshot_logs_operation_and_stable_key(self):
        self.ready()
        answer = EncoderChatMessage.objects.create(job=self.job, role="assistant", content="Old conversation", proposal={"payload": PAYLOAD}, base_revision=self.job.updated_at.isoformat())
        old_key = self.job.idempotency_key
        attempt = EncoderExecution.objects.create(job=self.job, connection=self.connection, tool_name=self.job.tool_name, payload=PAYLOAD, status="failed")
        with patch("encoder.services.chat.invoke_with_llm") as ai, patch("encoder.services.mcp_client.connector") as mcp:
            job = reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        self.assertEqual(job.cycle, 2)
        self.assertEqual(job.prepared_payload, {})
        self.assertEqual(job.idempotency_key, old_key)
        self.assertEqual(job.connection, self.connection)
        self.assertEqual(EncoderReset.objects.get().snapshot["prepared_payload"], PAYLOAD)
        self.assertTrue(EncoderChatMessage.objects.filter(pk=answer.pk).exists())
        self.assertTrue(EncoderExecution.objects.filter(pk=attempt.pk).exists())
        ai.assert_not_called()
        mcp.assert_not_called()
        response = self.client.get(reverse("ENCODER:workspace", args=[job.pk]))
        self.assertNotContains(response, "Old conversation")
        self.assertContains(response, "Saved drafts before reset")
        response = self.client.get(reverse("ENCODER:workspace", args=[job.pk]) + "?chat_history=1")
        self.assertContains(response, "Old conversation")
        self.assertContains(response, "Archived")
        self.assertNotContains(response, "Apply suggestion &amp; validate")

    def test_confirmation_and_revision_are_required_and_replay_is_blocked(self):
        revision = self.job.updated_at.isoformat()
        with self.assertRaises(ValidationError):
            reset(self.job.pk, revision)
        reset(self.job.pk, revision, confirmed=True)
        with self.assertRaises(ValidationError):
            reset(self.job.pk, revision, confirmed=True)
        self.assertEqual(EncoderReset.objects.count(), 1)

    def test_running_execution_and_chat_block_reset(self):
        self.job.status = "processing"
        self.job.save()
        with self.assertRaises(ValidationError):
            reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        self.job.status = "pending"
        self.job.save()
        EncoderChatMessage.objects.create(job=self.job, role="assistant", status="processing")
        with self.assertRaises(ValidationError):
            reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        self.assertFalse(EncoderReset.objects.exists())

    def test_completed_job_can_reset_without_erasing_success(self):
        self.ready()
        client = self.mock_connector()
        result = execution.execute(self.job.pk, execution.review_token(self.job), confirmed=True)
        self.job.refresh_from_db()
        reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        result.refresh_from_db()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.cycle, 1)
        client.call.assert_called_once()

    def test_old_suggestions_and_tokens_cannot_apply_to_new_cycle(self):
        token = self.ready()
        answer = EncoderChatMessage.objects.create(job=self.job, role="assistant", proposal={"payload": PAYLOAD}, base_revision=self.job.updated_at.isoformat())
        job = reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        job = mapping.save(job.pk, job.updated_at.isoformat(), payload=PAYLOAD)
        with self.assertRaises(ValidationError):
            chat.decide(job.pk, answer.pk, "accepted", job.updated_at.isoformat())
        with self.assertRaises(ValidationError):
            execution.execute(job.pk, token, confirmed=True)

    def test_unknown_outcomes_still_require_reconciliation_after_reset(self):
        token = self.ready()
        client = self.mock_connector(side_effect=TimeoutError)
        execution.execute(self.job.pk, token, confirmed=True)
        self.job.refresh_from_db()
        job = reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        job = mapping.save(job.pk, job.updated_at.isoformat(), payload=PAYLOAD)
        with self.assertRaisesMessage(ValidationError, "unknown"):
            execution.execute(job.pk, execution.review_token(job), confirmed=True)
        client.call.assert_called_once()
        client.call.side_effect = None
        result = execution.execute(job.pk, execution.review_token(job), confirmed=True, reconciled=True)
        self.assertEqual(result.cycle, 2)
        self.assertEqual(job.executions.count(), 2)

    def test_new_chat_context_excludes_archived_conversation(self):
        self.ready()
        EncoderChatMessage.objects.create(job=self.job, role="user", content="ARCHIVED_ONLY")
        job = reset(self.job.pk, self.job.updated_at.isoformat(), confirmed=True)
        with patch.dict(os.environ, {"CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": "mock"}), patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(return_value={"message": {"content": json.dumps({"message": "What is missing?", "issues": []})}})) as ai:
            answer = chat.ask(job.pk, "New conversation")
        self.assertEqual(answer.cycle, 2)
        self.assertNotIn("ARCHIVED_ONLY", json.dumps(ai.call_args.args[1]))

    def test_reset_endpoint_is_post_only_and_csrf_protected(self):
        url = reverse("ENCODER:job_action", args=[self.job.pk, "reset"])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True, HTTP_HOST="localhost").post(url, {"confirmed": "yes"}).status_code, 403)
        response = self.client.post(url, {"confirmed": "yes", "revision": self.job.updated_at.isoformat()})
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.cycle, 2)
