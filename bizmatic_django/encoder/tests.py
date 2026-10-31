"""Synthetic documents, mocked LLMs, and a real isolated stdio MCP fixture."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from document_extraction.models import DocExtractionLog, Document
from router.models import DocumentRoute, LLMRoutingLog, RoutingDestination, RoutingRule
from router.schemas.routing import ExecutionRequest
from router.services import handoff
from router.services.records import review
from .forms import MappingForm, PayloadForm
from .models import EncoderChatMessage, EncoderExecution, EncoderJob, EncoderMapping, MCPConnection
from .services import chat, discovery, execution, mapping, mcp_client, validation

SCHEMA = {"type": "object", "properties": {"product_code": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1}, "warehouse_id": {"type": "integer"}, "request_key": {"type": "string"}}, "required": ["product_code", "quantity", "warehouse_id"], "additionalProperties": False}
TOOL = {"name": "encode_receipt", "description": "Synthetic encoding", "inputSchema": SCHEMA}
PROFILES = {"fixture": {"command": sys.executable, "args": [str(Path(__file__).with_name("mock_server.py"))]}}
PAYLOAD = {"product_code": "TEST-1", "quantity": 2, "warehouse_id": 2}


@override_settings(ENCODER_LOCAL_ENABLED=True, ENCODER_STDIO_SERVERS=PROFILES, ALLOWED_HOSTS=["localhost", "testserver"])
class EncoderTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="localhost")
        self.document = Document.objects.create(file_name="synthetic.txt", document_type="text", storage_path="/tmp/unused-encoder-source.txt", processing_status="completed", review_status="approved")
        self.source = DocExtractionLog.objects.create(fk_document_no=self.document, markdown_text=json.dumps(PAYLOAD))
        self.destination = RoutingDestination.objects.create(name="Encoder", module_name="encoder", target_model="EncoderJob")
        self.log = LLMRoutingLog.objects.create(source_document=self.document, source_text_log=self.source, status="completed", source_revision=self.document.updated_at.isoformat(), input_text=self.source.markdown_text)
        self.route = DocumentRoute.objects.create(routing_log=self.log, destination=self.destination, review_status="approved")
        handoff.process(self.route.pk)
        self.job = EncoderJob.objects.get(route=self.route)
        self.connection = MCPConnection.objects.create(name="Synthetic", launch_profile="fixture", tools=[TOOL], approved_tools=[TOOL["name"]])

    def ready(self, payload=None):
        self.job.refresh_from_db()
        self.job = mapping.select(self.job.pk, self.connection, TOOL["name"], self.job.updated_at.isoformat())
        self.job = mapping.save(self.job.pk, self.job.updated_at.isoformat(), payload=payload or PAYLOAD)
        return execution.review_token(self.job)

    def mock_connector(self, **kwargs):
        client = Mock()
        client.discover.return_value = [TOOL]
        client.call.return_value = {"isError": False, "structuredContent": {"saved": True}}
        for name, value in kwargs.items():
            setattr(client.call, name, value)
        replacement = patch("encoder.services.mcp_client.connector", return_value=client)
        replacement.start()
        self.addCleanup(replacement.stop)
        return client

    def test_handoff_preserves_references_and_is_idempotent_without_provider_calls(self):
        with patch("encoder.services.mcp_client.connector") as client, patch("encoder.services.chat.invoke_with_llm") as llm:
            handoff.process(self.route.pk)
            self.assertEqual(EncoderJob.objects.filter(route=self.route).count(), 1)
            self.assertEqual(self.job.document, self.document)
            self.assertEqual(self.job.route.routing_log.source_text_log, self.source)
            self.assertEqual(self.job.status, "pending")
            client.assert_not_called()
            llm.assert_not_called()

    def test_automatic_draft_does_not_approve_route_or_source(self):
        self.route.review_status = "pending"
        self.route.processing_status = "pending"
        self.route.save()
        handoff.process(self.route.pk, automatic=True)
        self.route.refresh_from_db()
        self.assertEqual(self.route.review_status, "pending")
        self.assertEqual(self.route.processing_status, "completed")
        token = self.ready()
        client = self.mock_connector()
        with self.assertRaisesMessage(ValidationError, "Approve"):
            execution.execute(self.job.pk, token, confirmed=True)
        client.call.assert_not_called()

    def test_handoff_failure_can_be_retried_and_ap_ar_handlers_are_unchanged(self):
        for module, mode, target in [("accounts_payable", "ap", "SupplierSalesInvoice"), ("accounts_receivable", "ar", "CompanySalesInvoice")]:
            dest = RoutingDestination.objects.create(name=module, module_name=module, target_model=target)
            route = DocumentRoute.objects.create(routing_log=self.log, destination=dest, review_status="approved")
            with patch("accounts_receivable.services.extraction.execute_route") as handler:
                result = handoff.process(route.pk)
                self.assertEqual(result.processing_status, "completed")
                self.assertEqual(handler.call_args.args[0], mode)
                handler.assert_called_once()
        self.route.processing_status = "pending"
        self.route.save()
        with patch("encoder.services.handoff.create_job", side_effect=ValidationError("Temporary handoff failure")):
            self.assertEqual(handoff.process(self.route.pk).processing_status, "failed")
        self.assertEqual(handoff.process(self.route.pk).processing_status, "completed")
        self.assertEqual(EncoderJob.objects.count(), 1)

    def test_real_router_execution_creates_a_pending_encoder_draft(self):
        from uuid import uuid4
        from router.services.execution import execute
        RoutingRule.objects.create(name="Encode", destination=self.destination, instructions="Encode synthetic receipts")
        env = {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "mock"}
        output = {"message": {"content": json.dumps({"routes": [{"destination_id": self.destination.pk, "reason": "Synthetic match"}]})}}
        with patch.dict(os.environ, env), patch("router.services.llm.invoke", new=AsyncMock(return_value=output)):
            logs = execute(ExecutionRequest(request_id=uuid4(), document_ids=[self.document.pk], revisions={str(self.document.pk): self.document.updated_at.isoformat()}))
        job = EncoderJob.objects.get(route__routing_log=logs[0])
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.route.review_status, "pending")
        self.assertFalse(job.executions.exists())

    def test_router_response_distinguishes_draft_handoff_from_accounting_and_execution(self):
        from uuid import uuid4
        RoutingRule.objects.create(name="Encode", destination=self.destination, instructions="Encode synthetic receipts")
        output = {"message": {"content": json.dumps({"routes": [{"destination_id": self.destination.pk, "reason": "Synthetic match"}]})}}
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "mock"}), patch("router.services.llm.invoke", new=AsyncMock(return_value=output)):
            result = self.client.post(reverse("ROUTER:execute"), {"request_id": str(uuid4()), "document_ids": [self.document.pk], "revisions": {str(self.document.pk): self.document.updated_at.isoformat()}}, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["encoder"]["completed"], 1)
        self.assertEqual(result.json()["accounting"]["completed"], 0)
        self.assertIn("Encoder draft handoff", result.json()["message"])
        self.assertFalse(EncoderExecution.objects.exists())

    def test_discovery_never_approves_new_tools_and_revokes_changed_schemas(self):
        other = {"name": "other", "inputSchema": {"type": "object"}}
        client = self.mock_connector()
        client.discover.return_value = [TOOL, other]
        connection = discovery.discover(self.connection)
        self.assertEqual(connection.approved_tools, [TOOL["name"]])
        changed = {**TOOL, "inputSchema": {"type": "object"}}
        client.discover.return_value = [changed]
        connection = discovery.discover(connection)
        self.assertEqual(connection.approved_tools, [])
        client.call.assert_not_called()

    def test_discovery_failure_and_missing_credentials_are_clear_and_persisted(self):
        client = self.mock_connector()
        client.discover.side_effect = mcp_client.MCPError("Server unavailable")
        with self.assertRaises(ValidationError):
            discovery.discover(self.connection)
        self.connection.refresh_from_db()
        self.assertIn("unavailable", self.connection.discovery_error)
        with self.settings(ENCODER_STDIO_SERVERS={"fixture": {**PROFILES["fixture"], "env": ["ENCODER_TEST_MISSING_SECRET"]}}):
            with self.assertRaisesMessage(ValidationError, "ENCODER_TEST_MISSING_SECRET"):
                mcp_client.specification(self.connection)

    def test_mapping_defaults_transforms_custom_fields_and_original_preserved(self):
        rules = {"product_code": {"source": "product_code", "transform": "lower"}, "quantity": {"source": "quantity", "transform": "integer"}, "warehouse_id": {"default": 3}}
        self.ready()
        self.job = mapping.save(self.job.pk, self.job.updated_at.isoformat(), mappings=rules, reusable=True)
        self.assertEqual(self.job.prepared_payload, {"product_code": "test-1", "quantity": 2, "warehouse_id": 3})
        self.assertEqual(EncoderMapping.objects.get().field_mappings, rules)
        self.log.refresh_from_db()
        self.assertEqual(self.log.input_text, self.source.markdown_text)
        self.job = mapping.save(self.job.pk, self.job.updated_at.isoformat(), payload=PAYLOAD)
        self.assertEqual(self.job.prepared_payload, PAYLOAD)
        self.assertEqual(self.job.status, "ready")
        payload, issues = mapping.build({"items": [{"quantity": "1.5"}], "date": "31/12/2026"}, {"quantity": {"source": "items.0.quantity", "transform": "integer"}, "date": {"source": "date", "transform": "date_dmy"}})
        self.assertEqual(payload, {"date": "2026-12-31"})
        self.assertEqual(issues[0]["field"], "quantity")

    def test_missing_values_are_flagged_and_stale_manual_corrections_blocked(self):
        self.ready()
        old_revision = self.job.updated_at.isoformat()
        self.job = mapping.save(self.job.pk, old_revision, payload={"quantity": "two"})
        self.assertEqual(self.job.status, "needs_review")
        self.assertGreaterEqual(len(self.job.validation_errors), 3)
        with self.assertRaisesMessage(ValidationError, "changed"):
            mapping.save(self.job.pk, old_revision, payload=PAYLOAD)

    def test_nonfinite_manual_values_are_rejected_before_json_storage(self):
        self.ready()
        with self.assertRaisesMessage(ValidationError, "finite numbers"):
            mapping.save(self.job.pk, self.job.updated_at.isoformat(), payload={**PAYLOAD, "quantity": float("nan")})
        self.job.refresh_from_db()
        self.assertEqual(self.job.prepared_payload, PAYLOAD)

    def test_execution_requires_confirmation_and_signed_unchanged_payload(self):
        token = self.ready()
        client = self.mock_connector()
        for confirmed, reviewed in [(False, token), (True, "forged")]:
            with self.assertRaises(ValidationError):
                execution.execute(self.job.pk, reviewed, confirmed=confirmed)
        self.job = mapping.save(self.job.pk, self.job.updated_at.isoformat(), payload={**PAYLOAD, "quantity": 9})
        with self.assertRaisesMessage(ValidationError, "changed"):
            execution.execute(self.job.pk, token, confirmed=True)
        self.assertFalse(EncoderExecution.objects.exists())
        client.call.assert_not_called()

    def test_success_replay_and_completed_edit_protection(self):
        token = self.ready()
        client = self.mock_connector()
        attempt = execution.execute(self.job.pk, token, confirmed=True)
        self.assertEqual(attempt.status, "completed")
        self.assertEqual(attempt.payload, PAYLOAD)
        self.assertEqual(execution.execute(self.job.pk, token, confirmed=True).pk, attempt.pk)
        client.call.assert_called_once_with(TOOL["name"], PAYLOAD, SCHEMA)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "completed")
        with self.assertRaises(ValidationError):
            mapping.save(self.job.pk, self.job.updated_at.isoformat(), payload=PAYLOAD)
        self.assertContains(self.client.get(reverse("ENCODER:execution_detail", args=[attempt.pk])), '&quot;saved&quot;: true')

    def test_stale_source_superseded_route_and_unapproved_source_cannot_execute(self):
        for change in ("source", "new_route", "review"):
            with self.subTest(change=change):
                token = self.ready()
                if change == "source":
                    self.document.save()
                elif change == "new_route":
                    LLMRoutingLog.objects.create(source_document=self.document, status="completed")
                else:
                    self.document.review_status = "pending"
                    self.document.save(update_fields=["review_status"])
                with self.assertRaises(ValidationError):
                    execution.execute(self.job.pk, token, confirmed=True)
        self.assertFalse(EncoderExecution.objects.exists())

    def test_revoked_tool_changed_connection_and_live_schema_block_calls(self):
        token = self.ready()
        client = self.mock_connector()
        self.connection.enabled = False
        self.connection.save()
        with self.assertRaises(ValidationError):
            execution.execute(self.job.pk, token, confirmed=True)
        self.connection.enabled = True
        self.connection.save()
        self.job.refresh_from_db()
        token = execution.review_token(self.job)
        client.discover.return_value = [{**TOOL, "inputSchema": {"type": "object"}}]
        attempt = execution.execute(self.job.pk, token, confirmed=True)
        self.assertEqual(attempt.status, "failed")
        client.call.assert_not_called()

    def test_timeout_unknown_outcome_needs_reconciliation_and_retry_is_explicit(self):
        token = self.ready()
        client = self.mock_connector(side_effect=mcp_client.MCPError("MCP request timed out"))
        attempt = execution.execute(self.job.pk, token, confirmed=True)
        self.assertEqual(attempt.status, "unknown")
        self.assertEqual(client.call.call_count, 1)
        token = self.ready()
        with self.assertRaisesMessage(ValidationError, "Verify externally"):
            execution.execute(self.job.pk, token, confirmed=True)
        client.call.side_effect = None
        result = execution.execute(self.job.pk, token, confirmed=True, reconciled=True)
        self.assertEqual(result.status, "completed")
        attempt.refresh_from_db()
        self.assertIsNotNone(attempt.reconciled_at)

    def test_idempotent_retry_reuses_exact_payload_and_stable_key(self):
        EncoderMapping.objects.create(connection=self.connection, tool_name=TOOL["name"], idempotency_field="request_key")
        token = self.ready()
        client = self.mock_connector(side_effect=mcp_client.MCPError("Timeout"))
        first = execution.execute(self.job.pk, token, confirmed=True)
        token = self.ready()
        client.call.side_effect = None
        second = execution.execute(self.job.pk, token, confirmed=True)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(second.payload["request_key"], str(self.job.idempotency_key))

    def test_tool_error_preserves_response_and_no_automatic_retry(self):
        token = self.ready()
        client = self.mock_connector(return_value={"isError": True, "content": [{"type": "text", "text": "Warehouse unsupported"}]})
        attempt = execution.execute(self.job.pk, token, confirmed=True)
        self.assertEqual(attempt.status, "unknown")
        self.assertIn("Warehouse unsupported", json.dumps(attempt.response))
        self.assertEqual(client.call.call_count, 1)

    def test_chat_is_multi_turn_and_requires_separate_approval_without_execution(self):
        self.ready({"product_code": "TEST-1", "quantity": 2})
        output = {"message": {"content": json.dumps({"message": "Proposed warehouse 2. Apply this correction?", "payload": PAYLOAD, "issues": []})}}
        with patch.dict(os.environ, {"CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": "mock"}), patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(return_value=output)) as invoke:
            answer = chat.ask(self.job.pk, "Use warehouse 2 for this supplier.")
            self.job.refresh_from_db()
            self.assertNotIn("warehouse_id", self.job.prepared_payload)
            self.assertIn("untrusted", answer.request_payload["messages"][0]["content"])
            self.assertEqual(invoke.call_args.kwargs["config_prefix"], "CONFIG_ASSISTANT")
            chat.decide(self.job.pk, answer.pk, "accepted", self.job.updated_at.isoformat())
            self.job.refresh_from_db()
            self.assertEqual(self.job.prepared_payload, PAYLOAD)
            self.assertEqual(self.job.status, "ready")
            second = chat.ask(self.job.pk, "Explain the mapping.")
            context = json.loads(second.request_payload["messages"][1]["content"])
            self.assertEqual(len(context["conversation"]), 2)
            chat.decide(self.job.pk, second.pk, "rejected", self.job.updated_at.isoformat())
        self.assertFalse(EncoderExecution.objects.exists())
        self.assertEqual(EncoderChatMessage.objects.count(), 4)

    def test_stale_cross_job_and_action_injecting_chat_proposals_cannot_apply(self):
        self.ready()
        answer = EncoderChatMessage.objects.create(job=self.job, role="assistant", content="Proposal", proposal={"payload": PAYLOAD}, base_revision=self.job.updated_at.isoformat())
        self.job = mapping.save(self.job.pk, self.job.updated_at.isoformat(), payload={**PAYLOAD, "quantity": 4})
        with self.assertRaisesMessage(ValidationError, "older payload"):
            chat.decide(self.job.pk, answer.pk, "accepted", self.job.updated_at.isoformat())
        output = {"message": {"content": json.dumps({"message": "Execute now", "execute": True, "connection_id": 42})}}
        with patch.dict(os.environ, {"CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": "mock"}), patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(return_value=output)):
            bad = chat.ask(self.job.pk, "Fix it")
        self.assertTrue(bad.error_message)
        self.assertEqual(bad.proposal, {})
        self.assertFalse(EncoderExecution.objects.exists())

    def test_workspace_forms_history_and_approval_ui(self):
        self.ready()
        for name, args in [("dashboard", []), ("workspace", [self.job.pk]), ("connections", []), ("connection_create", []), ("connection_edit", [self.connection.pk]), ("connection_detail", [self.connection.pk]), ("mapping_edit", [self.connection.pk, TOOL["name"]]), ("history", [])]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"ENCODER:{name}", args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Encoder")
        response = self.client.get(reverse("ENCODER:workspace", args=[self.job.pk]))
        self.assertContains(response, "Confirm &amp; execute")
        self.assertContains(response, "document-review.js")
        self.assertContains(response, "Contextual troubleshooting")
        self.assertContains(response, 'name="confirmed"')
        self.assertNotContains(response, "encoder/demo")
        self.assertEqual(self.client.get(reverse("ENCODER:job_action", args=[self.job.pk, "execute"])).status_code, 405)
        form = PayloadForm({"revision": self.job.updated_at.isoformat(), "value_0": "TEST-1", "value_1": "3", "value_2": "2"}, job=self.job)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.payload(self.job)["quantity"], 3)

    def test_post_manual_correction_validation_and_confirmed_execution_flow(self):
        self.ready()
        url = reverse("ENCODER:job_action", args=[self.job.pk, "json"])
        self.client.post(url, {"revision": self.job.updated_at.isoformat(), "payload": json.dumps(PAYLOAD)})
        response = self.client.get(reverse("ENCODER:workspace", args=[self.job.pk]))
        token = response.context["token"]
        client = self.mock_connector()
        url = reverse("ENCODER:job_action", args=[self.job.pk, "execute"])
        self.client.post(url, {"token": token})
        client.call.assert_not_called()
        self.client.post(url, {"token": token, "confirmed": "yes"})
        self.assertEqual(EncoderExecution.objects.get().status, "completed")
        self.assertContains(self.client.get(reverse("ENCODER:history")), self.document.file_name)

    def test_loopback_gate_no_login_and_csrf_protection(self):
        url = reverse("ENCODER:dashboard")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url, REMOTE_ADDR="203.0.113.4").status_code, 403)
        self.assertEqual(self.client.get(url, REMOTE_ADDR="invalid").status_code, 403)
        self.assertEqual(self.client.get(url, HTTP_HOST="testserver").status_code, 403)
        with self.settings(ENCODER_LOCAL_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 403)
        strict = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.assertEqual(strict.post(reverse("ENCODER:job_action", args=[self.job.pk, "execute"]), {}).status_code, 403)

    def test_draft_routes_remain_rejectable_and_can_be_reopened(self):
        from router.services.pages import route as serialize
        self.route.refresh_from_db()
        self.assertFalse(serialize(self.route)["review_locked"])
        result = review(self.route.pk, {"revision": self.route.updated_at.isoformat(), "decision": "rejected"})
        self.assertEqual(result.review_status, "rejected")
        token = self.ready()
        with self.assertRaises(ValidationError):
            execution.execute(self.job.pk, token, confirmed=True)
        result = review(self.route.pk, {"revision": result.updated_at.isoformat(), "decision": "approved"})
        self.assertEqual(result.review_status, "approved")

    def test_processing_external_job_locks_route_and_blocks_new_routing(self):
        from router.services.pages import route as serialize
        self.job.status = "processing"
        self.job.save()
        self.route.refresh_from_db()
        self.assertTrue(serialize(self.route)["review_locked"])
        with self.assertRaises(ValidationError):
            review(self.route.pk, {"revision": self.route.updated_at.isoformat(), "decision": "rejected"})
        from uuid import uuid4
        from router.services.execution import execute
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "mock"}):
            with self.assertRaisesMessage(ValidationError, "Encoder execution"):
                execute(ExecutionRequest(request_id=uuid4(), document_ids=[self.document.pk], revisions={str(self.document.pk): self.document.updated_at.isoformat()}))

    def test_recover_interrupted_attempt_never_invokes_tool(self):
        from io import StringIO
        from django.core.management import call_command, CommandError
        self.ready()
        attempt = EncoderExecution.objects.create(job=self.job, connection=self.connection, tool_name=TOOL["name"], payload=PAYLOAD)
        self.job.status = "processing"
        self.job.save()
        with self.assertRaises(CommandError):
            call_command("recover_encoder_execution", attempt.pk)
        client = self.mock_connector()
        call_command("recover_encoder_execution", attempt.pk, confirm_process_stopped=True, stdout=StringIO())
        attempt.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(attempt.status, "unknown")
        self.assertEqual(self.job.status, "failed")
        client.call.assert_not_called()


    def test_exact_json_fields_are_mapped_without_guessing_and_enums_use_selects(self):
        job = mapping.select(self.job.pk, self.connection, TOOL["name"], self.job.updated_at.isoformat())
        self.assertEqual(job.prepared_payload, PAYLOAD)
        self.assertEqual(job.status, "ready")
        self.assertNotIn("request_key", job.prepared_payload)
        job.tool_schema = {"properties": {"currency": {"enum": ["PHP", "USD"]}, "approved": {"type": "boolean"}, "lines": {"type": "array"}}}
        job.prepared_payload = {"currency": "PHP", "approved": False, "lines": []}
        form = PayloadForm({"revision": job.updated_at.isoformat(), "value_0": '\"USD\"', "value_1": "false", "value_2": "[]"}, job=job)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.payload(job), {"currency": "USD", "approved": False, "lines": []})
        self.assertIn("<select", str(form["value_0"]))

    def test_mapping_selectors_build_reusable_rules_and_profile_is_not_an_arbitrary_command(self):
        from .forms import ConnectionForm
        self.ready()
        data = {"revision": self.job.updated_at.isoformat(), "source_0": "product_code", "transform_0": "upper",
                "source_1": "quantity", "transform_1": "integer", "source_2": "", "default_2": "2", "transform_2": "identity", "source_3": "", "transform_3": "identity"}
        form = MappingForm(data, job=self.job)
        self.assertTrue(form.is_valid(), form.errors)
        values, issues = mapping.build(mapping.source_data(self.job), form.mappings())
        self.assertEqual(values, PAYLOAD)
        self.assertEqual(issues, [])
        form = ConnectionForm({"name": "Unsafe", "launch_profile": "sh -c arbitrary-command", "timeout_seconds": 3, "enabled": True})
        self.assertFalse(form.is_valid())
        self.assertIn("command", form.errors)

    def test_distinct_confirmation_cannot_execute_while_first_call_is_processing(self):
        token = self.ready()
        second_token = execution.review_token(self.job)
        client = self.mock_connector()
        def concurrent_call(*args):
            with self.assertRaises(ValidationError):
                execution.execute(self.job.pk, second_token, confirmed=True)
            return {"isError": False}
        client.call.side_effect = concurrent_call
        first = execution.execute(self.job.pk, token, confirmed=True)
        self.assertEqual(first.status, "completed")
        self.assertEqual(client.call.call_count, 1)
        self.assertEqual(EncoderExecution.objects.count(), 1)

    def test_connection_configuration_discovery_and_explicit_tool_permission_forms(self):
        url = reverse("ENCODER:connection_create")
        client = self.mock_connector()
        response = self.client.post(url, {"name": "New fixture", "command": sys.executable, "arguments": "[]", "timeout_seconds": "5", "enabled": "on"})
        self.assertEqual(response.status_code, 302)
        connection = MCPConnection.objects.get(name="New fixture")
        client = self.mock_connector()
        url = reverse("ENCODER:connection_detail", args=[connection.pk])
        self.client.post(url, {"intent": "discover"})
        connection.refresh_from_db()
        self.assertEqual(connection.tools, [TOOL])
        self.assertEqual(connection.approved_tools, [])
        self.client.post(url, {"intent": "approve", "revision": connection.updated_at.isoformat(), "approved_tools": [TOOL["name"]]})
        connection.refresh_from_db()
        self.assertEqual(connection.approved_tools, [TOOL["name"]])
        self.client.post(url, {"intent": "approve", "revision": connection.updated_at.isoformat(), "approved_tools": ["not_discovered"]})
        connection.refresh_from_db()
        self.assertEqual(connection.approved_tools, [TOOL["name"]])
        client.call.assert_not_called()


    def test_assistant_logs_usage_and_failed_parse_keeps_tokens(self):
        self.ready()
        output = {"message": {"content": json.dumps({"message": "Review this correction.", "payload": PAYLOAD})}, "prompt_eval_count": 111, "eval_count": 27}
        with patch.dict(os.environ, {"CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": "synthetic"}), patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(return_value=output)) as invoke:
            answer = chat.ask(self.job.pk, "Help with the mapping")
            self.assertEqual((answer.status, answer.input_tokens, answer.output_tokens), ("completed", 111, 27))
            self.assertEqual(answer.model_name, "synthetic")
            self.assertIsNotNone(answer.processing_time_ms)
            self.assertEqual(answer.response_payload, output)
            invoke.return_value = {**output, "message": {"content": "invalid JSON"}}
            failed = chat.ask(self.job.pk, "Try again")
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.error_code, "invalid_response")
            self.assertEqual(failed.input_tokens, 111)
        self.assertFalse(EncoderExecution.objects.exists())
        for name, args in [("llm_logs", []), ("llm_log_detail", [answer.pk]), ("llm_log_detail", [failed.pk])]:
            self.assertEqual(self.client.get(reverse("ENCODER:" + name, args=args)).status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.prepared_payload, PAYLOAD)

    def test_timeout_and_authentication_failures_are_sanitized_with_unknown_usage(self):
        import httpx
        request = httpx.Request("POST", "https://example.test/chat")
        errors = [(httpx.ReadTimeout("secret detail"), "timeout"), (httpx.HTTPStatusError("secret detail", request=request, response=httpx.Response(401, request=request)), "authentication")]
        for error, code in errors:
            with patch.dict(os.environ, {"CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": "synthetic"}), patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(side_effect=error)):
                answer = chat.ask(self.job.pk, "Help")
                self.assertEqual(answer.status, "failed")
                self.assertEqual(answer.error_code, code)
                self.assertIsNone(answer.input_tokens)
                self.assertNotIn("secret detail", answer.error_message)


class SchemaTests(SimpleTestCase):
    def test_required_nested_arrays_types_enum_formats_and_custom_fields(self):
        self.assertEqual(validation.errors(PAYLOAD, SCHEMA), [])
        self.assertTrue(validation.errors({**PAYLOAD, "quantity": True}, SCHEMA))
        self.assertTrue(validation.errors({**PAYLOAD, "quantity": float("nan")}, SCHEMA))
        schema = {"type": "object", "properties": {"date": {"type": "string", "format": "date"}, "lines": {"type": "array", "items": {"$ref": "#/$defs/line"}}}, "$defs": {"line": {"type": "object", "properties": {"currency": {"enum": ["PHP", "USD"]}}, "required": ["currency"]}}}
        errors = validation.errors({"date": "2026-02-30", "lines": [{"currency": "INVALID"}]}, schema)
        self.assertEqual(len(errors), 2)
        with self.assertRaises(ValidationError):
            validation.errors({}, {"$ref": "https://example.invalid/schema"})


@override_settings(ENCODER_LOCAL_ENABLED=True, ENCODER_STDIO_SERVERS=PROFILES)
class StdioIntegrationTests(SimpleTestCase):
    def connection(self, **kwargs):
        return MCPConnection(name="Isolated fixture", launch_profile="fixture", timeout_seconds=5, **kwargs)

    def test_actual_sdk_stdio_discovery_and_tool_invocation(self):
        client = mcp_client.StdioConnector(self.connection())
        tools = client.discover()
        tool = next(row for row in tools if row["name"] == "encode_receipt")
        self.assertIn("warehouse_id", tool["inputSchema"]["required"])
        result = client.call("encode_receipt", PAYLOAD, tool["inputSchema"])
        self.assertFalse(result.get("isError"))
        self.assertTrue(result["structuredContent"]["saved"])

    def test_actual_sdk_server_tool_failure_and_timeout(self):
        connection = self.connection()
        client = mcp_client.StdioConnector(connection)
        tools = client.discover()
        tool = next(row for row in tools if row["name"] == "encode_receipt")
        result = client.call("encode_receipt", {**PAYLOAD, "quantity": -1}, tool["inputSchema"])
        self.assertTrue(result["isError"])
        slow = next(row for row in tools if row["name"] == "slow_operation")
        connection.timeout_seconds = 2
        with self.assertRaisesMessage(ValidationError, "timed out"):
            mcp_client.StdioConnector(connection).call("slow_operation", {}, slow["inputSchema"])


class TransportErrorTests(SimpleTestCase):
    @override_settings(ENCODER_LOCAL_ENABLED=True, ENCODER_STDIO_SERVERS=PROFILES)
    def test_sdk_timeout_is_reported_without_raw_server_error_text(self):
        from mcp.shared.exceptions import McpError
        from mcp.types import ErrorData
        client = mcp_client.StdioConnector(MCPConnection(launch_profile="fixture"))
        with patch.object(client, "_run", new=AsyncMock(side_effect=McpError(ErrorData(code=408, message="secret-server-detail")))):
            with self.assertRaisesMessage(ValidationError, "timed out") as error:
                client.discover()
        self.assertNotIn("secret-server-detail", str(error.exception))


@override_settings(ENCODER_LOCAL_ENABLED=True, ALLOWED_HOSTS=["localhost"])
class FrontendConnectionTests(TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from cryptography.fernet import Fernet
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        key = Path(self.directory.name) / "key"
        key.write_bytes(Fernet.generate_key())
        key.chmod(0o600)
        override = self.settings(DB_EXTRACTION_CREDENTIAL_KEY_FILE=key)
        override.enable()
        self.addCleanup(override.disable)
        self.client = Client(HTTP_HOST="localhost")
        self.data = {"name": "Frontend MCP", "command": sys.executable, "arguments": json.dumps(PROFILES["fixture"]["args"]), "working_directory": "", "environment": '{"ERP_API_KEY":"synthetic-secret"}', "enabled": "on", "timeout_seconds": 5}

    def test_real_frontend_test_discovers_without_saving_or_exposing_credentials(self):
        response = self.client.post(reverse("ENCODER:connection_create"), {**self.data, "intent": "test"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connection successful")
        self.assertNotContains(response, "synthetic-secret")
        self.assertFalse(MCPConnection.objects.exists())

    def test_save_encrypts_credentials_preserves_blanks_and_resets_permissions_on_change(self):
        from django.db import connection as db
        with patch("encoder.services.mcp_client.connector") as factory:
            factory.return_value.discover.return_value = [TOOL]
            response = self.client.post(reverse("ENCODER:connection_create"), self.data)
            self.assertEqual(response.status_code, 302)
            row = MCPConnection.objects.get()
            with db.cursor() as cursor:
                cursor.execute("SELECT environment FROM encoder_mcpconnection WHERE id = %s", [row.pk])
                stored = cursor.fetchone()[0]
            self.assertTrue(stored.startswith("fernet:v1:"))
            self.assertNotIn("synthetic-secret", stored)
            row.approved_tools = [TOOL["name"]]
            row.save()
            url = reverse("ENCODER:connection_edit", args=[row.pk])
            data = {**self.data, "environment": "", "revision": row.updated_at.isoformat()}
            self.assertEqual(self.client.post(url, data).status_code, 302)
            row.refresh_from_db()
            self.assertEqual(json.loads(row.environment)["ERP_API_KEY"], "synthetic-secret")
            self.assertEqual(row.approved_tools, [TOOL["name"]])
            data.update(command="different-server", revision=row.updated_at.isoformat())
            response = self.client.post(url, data)
            self.assertContains(response, "Launch details changed")
            factory.reset_mock()
            data["clear_environment"] = "on"
            self.assertEqual(self.client.post(url, data).status_code, 302)
            row.refresh_from_db()
            self.assertEqual(row.approved_tools, [])
            self.assertEqual(row.environment, "")
            factory.return_value.call.assert_not_called()

    def test_failed_test_invalid_json_and_missing_key_never_save(self):
        url = reverse("ENCODER:connection_create")
        for changes in ({"arguments": '"not-an-array"'}, {"environment": '{"KEY":4}'}):
            response = self.client.post(url, {**self.data, **changes})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(MCPConnection.objects.exists())
        with self.settings(DB_EXTRACTION_CREDENTIAL_KEY_FILE=Path(self.directory.name)/"missing"):
            response = self.client.post(url, self.data)
            self.assertContains(response, "credential key is unavailable")
        with patch("encoder.services.mcp_client.connector") as factory:
            factory.return_value.discover.side_effect = mcp_client.MCPError("Server unavailable")
            response = self.client.post(url, self.data)
            self.assertContains(response, "Server unavailable")
        self.assertFalse(MCPConnection.objects.exists())


@override_settings(ENCODER_LOCAL_ENABLED=True, ALLOWED_HOSTS=["localhost"])
class HTTPConnectionTests(TestCase):
    def setUp(self):
        FrontendConnectionTests.setUp(self)
        self.data = {"name": "HTTP fixture", "transport": "streamable_http", "server_url": "https://example.test/mcp", "bearer_token_env_var": "ENCODER_HTTP_TEST_TOKEN", "http_headers": '{"X-API-Key":"synthetic-header-secret"}', "env_http_headers": '{"X-Tenant":"ENCODER_HTTP_TEST_TENANT"}', "timeout_seconds": 5, "enabled": "on"}
        self.env = patch.dict(os.environ, {"ENCODER_HTTP_TEST_TOKEN": "synthetic-bearer", "ENCODER_HTTP_TEST_TENANT": "synthetic-tenant"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_http_form_requires_url_instead_of_command_and_hides_secrets(self):
        with patch("encoder.services.mcp_client.connector") as factory:
            factory.return_value.discover.return_value = [TOOL]
            response = self.client.post(reverse("ENCODER:connection_create"), self.data)
            self.assertEqual(response.status_code, 302)
        row = MCPConnection.objects.get()
        self.assertEqual(row.transport, "streamable_http")
        self.assertEqual(row.command, "")
        self.assertIsInstance(mcp_client.connector(row), mcp_client.StreamableHTTPConnector)
        spec = mcp_client.specification(row)
        self.assertEqual(spec.headers["Authorization"], "Bearer synthetic-bearer")
        self.assertEqual(spec.headers["X-Tenant"], "synthetic-tenant")
        response = self.client.get(reverse("ENCODER:connection_edit", args=[row.pk]))
        self.assertNotContains(response, "synthetic-header-secret")
        from django.db import connection as db
        with db.cursor() as cursor:
            cursor.execute("SELECT http_headers FROM encoder_mcpconnection WHERE id = %s", [row.pk])
            stored = cursor.fetchone()[0]
        self.assertTrue(stored.startswith("fernet:v1:"))
        self.assertNotIn("synthetic-header-secret", stored)
        row.approved_tools = [TOOL["name"]]
        row.save()
        data = {**self.data, "http_headers": "", "server_url": "https://other.test/mcp", "revision": row.updated_at.isoformat()}
        response = self.client.post(reverse("ENCODER:connection_edit", args=[row.pk]), data)
        self.assertContains(response, "Re-enter or clear saved headers")
        with patch("encoder.services.mcp_client.connector") as factory:
            factory.return_value.discover.return_value = [TOOL]
            response = self.client.post(reverse("ENCODER:connection_edit", args=[row.pk]), {**data, "clear_http_headers": "on"})
            self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.approved_tools, [])

    def test_http_validation_missing_credentials_invalid_urls_and_header_injection(self):
        from .forms import ConnectionForm
        for changes in ({"server_url": ""}, {"server_url": "file:///tmp/mcp"}, {"server_url": "https://user:secret@example.test/mcp"}, {"bearer_token_env_var": "ENCODER_MISSING_HTTP_TOKEN"}, {"http_headers": '{"X-Auth":"bad\\r\\nInjected: bad"}'}, {"env_http_headers": '[]'}, {"http_headers": '{"Authorization":"competing-token"}'}):
            form = ConnectionForm({**self.data, **changes})
            self.assertFalse(form.is_valid(), changes)
        self.assertFalse(MCPConnection.objects.exists())


@override_settings(ENCODER_LOCAL_ENABLED=True)
class HTTPTransportIntegrationTests(SimpleTestCase):
    def test_real_sdk_streamable_http_discovery_and_invocation_without_network(self):
        import httpx
        from asgiref.sync import async_to_sync
        from mcp.server.fastmcp import FastMCP
        from mcp.client.streamable_http import streamablehttp_client as sdk_transport
        server = FastMCP("HTTP synthetic fixture", stateless_http=True, json_response=True)
        @server.tool()
        def sample(value: int) -> int:
            return value + 1
        app = server.streamable_http_app()
        requests = []
        async def record(request):
            requests.append(dict(request.headers))
        def factory(headers=None, timeout=None, auth=None):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=headers, timeout=timeout, auth=auth, event_hooks={"request": [record]})
        def transport(*args, **kwargs):
            return sdk_transport(*args, **kwargs, httpx_client_factory=factory)
        client = mcp_client.connector(MCPConnection(transport="streamable_http", server_url="http://127.0.0.1:8001/mcp", http_headers='{"X-API-Key":"fixture-secret"}'))
        async def run():
            async with server.session_manager.run():
                tools = await client._run()
                tool = next(row for row in tools if row["name"] == "sample")
                return await client._run(name="sample", payload={"value": 2}, schema=tool["inputSchema"])
        with patch("encoder.services.mcp_client.streamablehttp_client", side_effect=transport):
            result = async_to_sync(run)()
        self.assertFalse(result.get("isError"))
        self.assertTrue(any(row.get("x-api-key") == "fixture-secret" for row in requests))
        self.assertIn("3", json.dumps(result))


@override_settings(ENCODER_LOCAL_ENABLED=True)
class PassthroughTests(SimpleTestCase):
    def test_passthrough_resolves_at_launch_and_literal_values_override(self):
        row = MCPConnection(command="python", environment_passthrough=["ENCODER_PASSTHROUGH"], environment='{"OTHER":"literal"}')
        with patch.dict(os.environ, {"ENCODER_PASSTHROUGH": "server-value"}):
            self.assertEqual(mcp_client.specification(row).env, {"ENCODER_PASSTHROUGH": "server-value", "OTHER": "literal"})
            row.environment = '{"ENCODER_PASSTHROUGH":"explicit-value"}'
            self.assertEqual(mcp_client.specification(row).env["ENCODER_PASSTHROUGH"], "explicit-value")
        row.environment_passthrough = ["ENCODER_NOT_CONFIGURED_TEST"]
        with self.assertRaisesMessage(ValidationError, "Missing passthrough"):
            mcp_client.specification(row)
        row.environment_passthrough = {"not": "a list"}
        with self.assertRaisesMessage(ValidationError, "variable names"):
            mcp_client.specification(row)
