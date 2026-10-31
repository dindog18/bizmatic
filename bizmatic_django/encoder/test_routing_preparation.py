"""Rule-selected preparation uses saved text and never invokes a business tool."""
import json
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from document_extraction.models import DocExtractionLog, Document
from router.forms import RuleForm
from router.models import DocumentRoute, LLMRoutingLog, RoutingDestination, RoutingRule
from router.schemas.routing import ExecutionRequest, RoutingResponse
from router.services import execution as routing, handoff
from .models import EncoderExecution, EncoderJob, EncoderMapping, MCPConnection
from .services import chat, execution, mapping
from .tests import PAYLOAD, TOOL


@override_settings(ENCODER_LOCAL_ENABLED=True, ALLOWED_HOSTS=["localhost", "testserver"])
class RoutingPreparationTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(file_name="synthetic.txt", document_type="text", storage_path="/tmp/unused-encoder-source.txt", processing_status="completed", review_status="approved")
        self.source = DocExtractionLog.objects.create(fk_document_no=self.document, markdown_text=json.dumps(PAYLOAD))
        self.destination = RoutingDestination.objects.create(name="Encoder", module_name="encoder", target_model="EncoderJob")
        self.connection = MCPConnection.objects.create(name="Synthetic", tools=[TOOL], approved_tools=[TOOL["name"]])
        self.rule = RoutingRule.objects.create(name="Receipts", destination=self.destination, instructions="Match receipts", encoder_connection=self.connection, encoder_tool=TOOL["name"])
        self.env = patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "mock", "CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": "mock"})
        self.env.start()
        self.addCleanup(self.env.stop)
        # Any MCP access during preparation is a failure, including discovery.
        self.connector = patch("encoder.services.mcp_client.connector", side_effect=AssertionError("Unexpected MCP invocation"))
        self.connector.start()
        self.addCleanup(self.connector.stop)

    def run_route(self, *, rule_id=None):
        match = {"destination_id": self.destination.pk, "reason": "Synthetic receipt"}
        if rule_id is not None:
            match["rule_id"] = rule_id
        output = {"message": {"content": json.dumps({"routes": [match]})}}
        with patch("router.services.llm.invoke", new=AsyncMock(return_value=output)):
            logs = routing.execute(ExecutionRequest(request_id=uuid4(), document_ids=[self.document.pk], revisions={str(self.document.pk): self.document.updated_at.isoformat()}))
        return logs[0]

    def ai(self, payload, *, issues=None, mappings=None):
        proposal = {"message": "Please provide the missing warehouse." if issues else "Review the prepared values.", "payload": payload, "issues": issues or []}
        if mappings is not None:
            proposal["mappings"] = mappings
        return patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(return_value={"message": {"content": json.dumps(proposal)}, "prompt_eval_count": 100, "eval_count": 30}))

    def test_rule_form_requires_enabled_connection_and_permitted_tool(self):
        data = {"name": "Rule", "destination": self.destination.pk, "instructions": "Receipts", "is_active": True}
        for values in ({}, {"encoder_connection": self.connection.pk, "encoder_tool": "unknown"}):
            self.assertFalse(RuleForm({**data, **values}).is_valid())
        data.update(encoder_connection=self.connection.pk, encoder_tool=TOOL["name"])
        self.assertTrue(RuleForm(data).is_valid())
        self.connection.enabled = False
        self.connection.save()
        self.assertFalse(RuleForm(data).is_valid())

    def test_accounting_rule_clears_encoder_settings(self):
        destination = RoutingDestination.objects.create(name="AP", module_name="accounts_payable", target_model="SupplierSalesInvoice")
        form = RuleForm({"name": "AP", "destination": destination.pk, "instructions": "Supplier invoices", "encoder_connection": self.connection.pk, "encoder_tool": TOOL["name"]})
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertIsNone(saved.encoder_connection_id)
        self.assertEqual(saved.encoder_tool, "")

    def test_configuration_api_saves_selection_and_bootstrap_filters_unapproved_tools(self):
        self.connection.tools += [{**TOOL, "name": "not_permitted"}]
        self.connection.save()
        response = self.client.post(reverse("ROUTER:configuration_save", args=["rules"]), {"name": "Frontend rule", "destination_id": self.destination.pk, "instructions": "Receipts", "encoder_connection": self.connection.pk, "encoder_tool": TOOL["name"]}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        saved = RoutingRule.objects.get(name="Frontend rule")
        self.assertEqual(saved.encoder_connection, self.connection)
        state = self.client.get(reverse("ROUTER:rule_edit", args=[saved.pk])).context["router_state"]
        self.assertEqual(state["encoder_connections"][0]["tools"], [{"name": TOOL["name"], "label": TOOL["name"]}])
        row = next(row for row in state["rules"] if row["id"] == saved.pk)
        self.assertEqual(row["encoder_connection"], self.connection.pk)
        self.assertEqual(row["encoder_tool"], TOOL["name"])

    def test_saved_mapping_prepares_once_without_llm_and_still_requires_approval(self):
        EncoderMapping.objects.create(connection=self.connection, tool_name=TOOL["name"], field_mappings={key: {"source": key} for key in PAYLOAD})
        with patch("encoder.services.chat.ask") as ai:
            log = self.run_route(rule_id=self.rule.pk)
            job = EncoderJob.objects.get(route__routing_log=log)
            handoff.process(job.route_id)
        ai.assert_not_called()
        self.assertEqual(job.status, "ready")
        self.assertEqual(job.prepared_payload, PAYLOAD)
        self.assertEqual(job.connection, self.connection)
        self.assertEqual(job.route.review_status, "pending")
        self.assertEqual(job.route.encoder_config["rule_id"], self.rule.pk)
        with self.assertRaisesMessage(ValidationError, "Explicitly confirm"):
            execution.execute(job.pk, execution.review_token(job))
        with self.assertRaisesMessage(ValidationError, "Approve"):
            execution.execute(job.pk, execution.review_token(job), confirmed=True)
        self.assertFalse(EncoderExecution.objects.exists())
        response = self.client.get(reverse("ENCODER:workspace", args=[job.pk]), HTTP_HOST="localhost")
        self.assertContains(response, "Routed operation")
        self.assertNotContains(response, 'data-operation-form>')

    def test_missing_values_start_logged_chat_and_partial_draft_without_external_calls(self):
        self.source.markdown_text = "Receipt TEST-1; quantity 2. Warehouse is not shown."
        self.source.save()
        partial = {"product_code": "TEST-1", "quantity": 2}
        with self.ai(partial, issues=["Which warehouse should receive these items?"], mappings={"quantity": {"default": 2}}) as ai:
            log = self.run_route()
            job = EncoderJob.objects.get(route__routing_log=log)
            handoff.process(job.route_id)
            ai.assert_awaited_once()
        self.assertEqual(job.status, "needs_review")
        self.assertEqual(job.prepared_payload, partial)
        self.assertNotIn("warehouse_id", job.prepared_payload)
        self.assertEqual(job.field_mappings, {"quantity": {"default": 2}})
        self.assertTrue(any("warehouse" in row["message"] for row in job.validation_errors))
        answer = job.chat_messages.get(role="assistant")
        self.assertEqual((answer.decision, answer.status, answer.input_tokens, answer.output_tokens), ("prepared", "completed", 100, 30))
        self.assertEqual(job.chat_messages.first().role, "routing")
        self.assertEqual(log.input_text, self.source.markdown_text)
        self.assertFalse(job.executions.exists())
        response = self.client.get(reverse("ENCODER:workspace", args=[job.pk]), HTTP_HOST="localhost")
        self.assertContains(response, "Continue troubleshooting")
        self.assertContains(response, "Initial draft · Prepared automatically")
        self.assertContains(response, "Needs your input")
        self.assertContains(response, "Suggested values · AI prepared")
        self.assertContains(response, "Review warnings · omissions and uncertain values")

    def test_ai_preparation_can_produce_ready_draft_but_never_executes(self):
        self.source.markdown_text = "A receipt in Markdown with all required values."
        self.source.save()
        with self.ai(PAYLOAD):
            log = self.run_route()
        job = EncoderJob.objects.get(route__routing_log=log)
        self.assertEqual((job.status, job.prepared_payload), ("ready", PAYLOAD))
        self.assertFalse(job.executions.exists())

    def test_provider_timeout_keeps_job_reviewable_and_failure_logged(self):
        self.source.markdown_text = "Receipt with missing values."
        self.source.save()
        with patch("encoder.services.chat.invoke_with_llm", new=AsyncMock(side_effect=TimeoutError)):
            log = self.run_route()
        job = EncoderJob.objects.get(route__routing_log=log)
        self.assertEqual(job.status, "needs_review")
        self.assertIn("timed out", job.last_error)
        self.assertEqual(job.chat_messages.get(role="assistant").error_code, "timeout")
        self.assertEqual(job.route.processing_status, "completed")

    def test_revoked_permission_stops_preparation(self):
        self.connection.approved_tools = []
        self.connection.save()
        with patch("encoder.services.chat.ask") as ai:
            log = self.run_route()
        job = EncoderJob.objects.get(route__routing_log=log)
        ai.assert_not_called()
        self.assertEqual(job.status, "needs_review")
        self.assertIn("permitted", job.last_error)

    def test_routing_snapshot_survives_later_rule_changes(self):
        snapshot = routing.rule_snapshot()
        log = LLMRoutingLog.objects.create(source_document=self.document, source_text_log=self.source, source_revision=self.document.updated_at.isoformat(), input_text=self.source.markdown_text, rules_snapshot=snapshot)
        self.rule.encoder_tool = "changed_later"
        self.rule.save()
        result = RoutingResponse.model_validate({"routes": [{"destination_id": self.destination.pk, "rule_id": self.rule.pk, "reason": "Receipt"}]})
        routing._save_result(log, {}, result, None, 1)
        handoff.process_matches(log.pk)
        job = EncoderJob.objects.get(route__routing_log=log)
        self.assertEqual(job.tool_name, TOOL["name"])
        self.assertEqual(job.status, "ready")

    def test_specific_rule_selects_operation_and_ambiguous_legacy_response_stops(self):
        other = {**TOOL, "name": "encode_other"}
        self.connection.tools += [other]
        self.connection.approved_tools += [other["name"]]
        self.connection.save()
        other_rule = RoutingRule.objects.create(name="Other receipts", destination=self.destination, instructions="Other format", encoder_connection=self.connection, encoder_tool=other["name"])
        first = self.run_route(rule_id=other_rule.pk)
        self.assertEqual(EncoderJob.objects.get(route__routing_log=first).tool_name, other["name"])
        second = self.run_route()
        job = EncoderJob.objects.get(route__routing_log=second)
        self.assertEqual(job.status, "needs_review")
        self.assertIn("one matching Encoder rule", job.last_error)
        self.assertEqual(job.tool_name, "")

    def test_unconfigured_rule_id_is_rejected_before_handoff(self):
        log = self.run_route(rule_id=self.rule.pk + 1000)
        self.assertEqual(log.status, "failed")
        self.assertFalse(DocumentRoute.objects.filter(routing_log=log).exists())
        self.assertFalse(EncoderJob.objects.exists())

    def test_user_edits_during_ai_preparation_are_not_overwritten(self):
        self.source.markdown_text = "Markdown receipt."
        self.source.save()
        ask = chat.ask

        def concurrent_edit(job_id, *args, **kwargs):
            answer = ask(job_id, *args, **kwargs)
            job = EncoderJob.objects.get(pk=job_id)
            mapping.save(job_id, job.updated_at.isoformat(), payload={**PAYLOAD, "quantity": 9})
            return answer

        with self.ai(PAYLOAD), patch("encoder.services.handoff.chat.ask", side_effect=concurrent_edit):
            log = self.run_route()
        job = EncoderJob.objects.get(route__routing_log=log)
        self.assertEqual(job.prepared_payload["quantity"], 9)
        self.assertEqual(job.chat_messages.get(role="assistant").decision, "pending")
        self.assertFalse(job.executions.exists())
