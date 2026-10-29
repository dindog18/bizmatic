"""Execution tests use fake provider responses and a disposable Django database."""

import json
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from document_extraction.models import Batch, DocExtractionLog, Document, LLMExtractionLog
from .models import DocumentRoute, LLMRoutingLog, RoutingDestination, RoutingRule
from .services import execution, llm


class ExecutionTests(TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "routing-test",
                                                  "ROUTER_MAX_CONCURRENCY": "2", "ROUTER_MAX_DOCUMENTS": "100"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.batch = Batch.objects.create()
        self.document = self.make_document("Invoice.txt")
        self.ap = RoutingDestination.objects.create(name="Supplier invoice", module_name="accounts_payable", target_model="SupplierSalesInvoice")
        self.ar = RoutingDestination.objects.create(name="Company invoice", module_name="accounts_receivable", target_model="CompanySalesInvoice")
        for destination in (self.ap, self.ar):
            RoutingRule.objects.create(name=destination.name, destination=destination, instructions="Evaluate the issuer and recipient.")
        self.invoke = AsyncMock(return_value=self.response([self.ap.pk, self.ar.pk]))
        self.provider = patch("router.services.llm.invoke", self.invoke)
        self.provider.start()
        self.addCleanup(self.provider.stop)
        self.url = reverse("ROUTER:execute")

    def make_document(self, name, review="approved"):
        document = Document.objects.create(fk_batch_no=self.batch, file_name=name, document_type="text",
                                           storage_path="/tmp/unused-routing-source.txt", processing_status="completed", review_status=review)
        DocExtractionLog.objects.create(fk_document_no=document, markdown_text="Invoice INV-001 issued by supplier to company.")
        return document

    def response(self, ids):
        return {"message": {"content": json.dumps({"routes": [{"destination_id": pk, "reason": "Document matches configured rule.", "confidence": 0.9} for pk in ids]})},
                "prompt_eval_count": 100, "eval_count": 30, "done_reason": "stop"}

    def payload(self, documents=None, **values):
        documents = documents or [self.document]
        return {"request_id": str(uuid4()), "document_ids": [doc.pk for doc in documents],
                "revisions": {str(doc.pk): doc.updated_at.isoformat() for doc in documents}, **values}

    def post(self, data):
        return self.client.post(self.url, data, content_type="application/json")

    def test_multiple_destinations_are_saved_with_source_and_llm_snapshots(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 200, response.content)
        log = LLMRoutingLog.objects.get()
        self.assertEqual(log.status, "completed")
        self.assertEqual(set(log.routes.values_list("destination_id", flat=True)), {self.ap.pk, self.ar.pk})
        self.assertTrue(all(row.review_status == "pending" for row in log.routes.all()))
        self.assertEqual(log.source_text_log, self.document.text_logs.get())
        self.assertEqual(log.input_tokens, 100)
        self.assertEqual(log.output_tokens, 30)
        self.assertEqual(len(log.rules_snapshot), 2)
        self.assertEqual(log.response_payload, self.invoke.return_value)
        self.assertIn("Invoice INV-001", log.input_text)
        self.assertIn("untrusted data", log.prompt_text)
        self.assertFalse(log.confirmed_unapproved)
        self.document.refresh_from_db()
        self.assertEqual(self.document.review_status, "approved")
        self.assertEqual(self.document.processing_status, "completed")
        self.assertContains(self.client.get(reverse("DOC_EXTRACTION:document_detail", args=[self.document.pk])),
                            reverse("ROUTER:document", args=[self.document.pk]))

    def test_pending_and_rejected_require_explicit_override_on_server(self):
        for status in ("pending", "rejected"):
            document = self.make_document(status + ".txt", status)
            payload = self.payload([document])
            response = self.post(payload)
            self.assertEqual(response.status_code, 409)
            self.assertTrue(response.json()["confirmation_required"])
            self.assertFalse(document.routing_logs.exists())
            response = self.post({**payload, "allow_unapproved": True})
            self.assertEqual(response.status_code, 200)
            log = document.routing_logs.get()
            self.assertTrue(log.confirmed_unapproved)
            self.assertEqual(log.source_review_status, status)
            document.refresh_from_db()
            self.assertEqual(document.review_status, status)

    def test_stale_review_or_batch_membership_requires_fresh_confirmation(self):
        data = self.payload(batch_id=self.batch.pk)
        self.document.review_status = "pending"
        self.document.save()
        response = self.post({**data, "allow_unapproved": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["documents"][0]["review_status"], "pending")
        extra = self.make_document("new.txt")
        response = self.post(data)
        self.assertEqual({row["id"] for row in response.json()["documents"]}, {self.document.pk, extra.pk})
        self.assertFalse(LLMRoutingLog.objects.exists())
        self.invoke.assert_not_awaited()

    def test_batch_includes_every_document_and_rejects_hidden_unapproved(self):
        documents = [self.document] + [self.make_document(f"{index}.txt") for index in range(26)]
        documents[0].review_status = "pending"
        documents[0].save()
        response = self.post(self.payload(documents, batch_id=self.batch.pk))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(response.json()["documents"]), 27)
        self.invoke.assert_not_awaited()

    def test_retry_is_idempotent_and_rerun_retains_history(self):
        payload = self.payload()
        self.assertEqual(self.post(payload).status_code, 200)
        first = LLMRoutingLog.objects.get()
        self.assertEqual(self.post(payload).status_code, 200)
        self.assertEqual(LLMRoutingLog.objects.count(), 1)
        self.invoke.assert_awaited_once()
        self.assertEqual(self.post(self.payload()).status_code, 200)
        self.assertEqual(LLMRoutingLog.objects.count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.routes.count(), 2)

    def test_active_document_is_not_routed_twice(self):
        LLMRoutingLog.objects.create(source_document=self.document, status="processing")
        self.assertEqual(self.post(self.payload()).status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LLMRoutingLog.objects.create(source_document=self.document, status="queued")
        self.invoke.assert_not_awaited()

    def test_accurate_text_is_preferred_and_failed_ocr_is_ignored(self):
        accurate = self.document.text_logs.get()
        accurate.user_selected_accurate = True
        accurate.markdown_text = "Human verified invoice text"
        accurate.save()
        LLMExtractionLog.objects.create(fk_document_no=self.document, status="completed", markdown_text="Alternative OCR text")
        LLMExtractionLog.objects.create(fk_document_no=self.document, status="failed", markdown_text="Failed partial OCR")
        self.post(self.payload())
        log = LLMRoutingLog.objects.get()
        self.assertEqual(log.input_text, accurate.markdown_text)
        self.assertEqual(log.source_text_log_id, accurate.pk)

    def test_failed_sibling_retains_error_while_other_document_completes(self):
        second = self.make_document("second.txt")
        self.invoke.side_effect = [RuntimeError("Provider unavailable"), self.response([])]
        response = self.post(self.payload([self.document, second], batch_id=self.batch.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(LLMRoutingLog.objects.order_by("pk").values_list("status", flat=True)), ["failed", "completed"])
        self.assertIn("Provider unavailable", LLMRoutingLog.objects.order_by("pk").first().error_message)
        self.assertEqual(DocumentRoute.objects.count(), 0)

    def test_invalid_llm_results_fail_atomically_and_keep_raw_response(self):
        for routes in ([self.ap.pk, 999999], [self.ap.pk, self.ap.pk]):
            self.invoke.return_value = self.response(routes)
            response = self.post(self.payload())
            self.assertEqual(response.status_code, 200)
            log = LLMRoutingLog.objects.order_by("-pk").first()
            self.assertEqual(log.status, "failed")
            self.assertEqual(log.routes.count(), 0)
            self.assertTrue(log.response_text)
            self.assertEqual(log.response_payload, self.invoke.return_value)
        self.invoke.return_value = {"message": {"content": "not JSON"}}
        self.post(self.payload())
        self.assertEqual(LLMRoutingLog.objects.order_by("-pk").first().status, "failed")

    def test_disabled_destinations_and_rules_are_not_sent(self):
        self.ar.is_active = False
        self.ar.save()
        unused = RoutingDestination.objects.create(name="Unused", module_name="accounts_payable", target_model="CompanyPayment")
        RoutingRule.objects.create(name="Disabled rule", destination=unused, instructions="Do not send", is_active=False)
        self.invoke.return_value = self.response([self.ap.pk])
        self.post(self.payload())
        self.assertEqual([row["destination_id"] for row in LLMRoutingLog.objects.get().rules_snapshot], [self.ap.pk])

    def test_empty_text_or_missing_rules_create_no_attempts(self):
        self.document.text_logs.update(markdown_text="")
        self.assertEqual(self.post(self.payload()).status_code, 400)
        self.document.text_logs.update(markdown_text="Invoice")
        RoutingRule.objects.update(is_active=False)
        self.assertEqual(self.post(self.payload()).status_code, 400)
        self.assertFalse(LLMRoutingLog.objects.exists())
        self.invoke.assert_not_awaited()

    def test_oversized_input_busy_source_and_invalid_settings_fail_before_call(self):
        with patch.dict(os.environ, {"ROUTER_MAX_INPUT_CHARACTERS": "2"}):
            self.assertEqual(self.post(self.payload()).status_code, 400)
        self.document.processing_status = "processing"
        self.document.save()
        self.assertEqual(self.post(self.payload()).status_code, 400)
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "mistral"}):
            self.assertEqual(self.post(self.payload()).status_code, 400)
        self.assertFalse(LLMRoutingLog.objects.exists())
        self.invoke.assert_not_awaited()

    def test_csrf_and_post_are_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.payload(), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(self.url, "broken", content_type="application/json").status_code, 400)

    def test_review_is_persisted_and_rejects_source_changes(self):
        self.post(self.payload())
        route = DocumentRoute.objects.first()
        url = reverse("ROUTER:route_review", args=[route.pk])
        data = {"decision": "approved", "review_notes": "Checked source", "revision": route.updated_at.isoformat()}
        response = self.client.post(url, data, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        route.refresh_from_db()
        self.assertEqual(route.review_status, "approved")
        self.document.review_status = "pending"
        self.document.save()
        self.assertEqual(self.client.post(url, {**data, "revision": route.updated_at.isoformat(), "decision": "pending"}, content_type="application/json").status_code, 400)

    def test_native_provider_payloads_and_parsers(self):
        for provider in ("openai", "anthropic", "google", "ollama", "alibaba", "deepseek"):
            with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": provider, f"ROUTER_{provider.upper()}_MODEL": "routing-test"}):
                config = llm.settings()
                _, payload = llm.request_payload(config, "text", [])
                self.assertEqual(payload["model"], "routing-test")
        text = json.dumps({"routes": []})
        responses = {
            "openai": {"choices": [{"message": {"content": text}}]},
            "anthropic": {"content": [{"type": "text", "text": text}]},
            "google": {"candidates": [{"content": {"parts": [{"text": text}]}}]},
            "ollama": {"message": {"content": text}},
        }
        for provider, result in responses.items():
            self.assertEqual(llm.parse_response(provider, result, set()).routes, [])
        for confidence in (-1, 2, "0.5", float("nan")):
            result = {"message": {"content": json.dumps({"routes": [{"destination_id": self.ap.pk, "reason": "Match", "confidence": confidence}]})}}
            with self.assertRaises(ValueError):
                llm.parse_response("ollama", result, {self.ap.pk})
        with self.assertRaises(ValueError):
            llm.parse_response("ollama", {"message": {"content": text}, "done_reason": "length"}, set())

    def test_router_credentials_base_url_and_timeout_use_shared_transport(self):
        from asgiref.sync import async_to_sync
        from document_extraction.services import llm as transport

        with patch.dict(os.environ, {"ROUTER_OPENAI_API_KEY": "router-test-key", "ROUTER_OPENAI_BASE_URL": "https://router.example/v1", "DOC_EXTRACTION_OPENAI_API_KEY": "extraction-test-key"}), patch.object(transport, "_post", new_callable=AsyncMock) as post:
            post.return_value = {"choices": []}
            async_to_sync(transport.invoke_with_llm)("openai", {"model": "test-model"}, config_prefix="ROUTER", timeout=37)
            self.assertEqual(post.await_args.args[0], "https://router.example/v1/chat/completions")
            self.assertEqual(post.await_args.args[2], {"Authorization": "Bearer router-test-key"})
            self.assertEqual(post.await_args.kwargs, {"timeout": 37})
        with patch.dict(os.environ, {"ROUTER_OPENAI_API_KEY": "", "DOC_EXTRACTION_OPENAI_API_KEY": "extraction-test-key"}), patch.object(transport, "_post", new_callable=AsyncMock) as post:
            post.return_value = {"choices": []}
            async_to_sync(transport.invoke_with_llm)("openai", {"model": "test-model"}, config_prefix="ROUTER", timeout=37)
            self.assertEqual(post.await_args.args[2], {"Authorization": "Bearer extraction-test-key"})

    def test_preflight_rolls_back_entire_selection_if_one_document_has_no_text(self):
        missing = self.make_document("empty.txt")
        missing.text_logs.update(markdown_text="")
        self.assertEqual(self.post(self.payload([self.document, missing])).status_code, 400)
        self.assertFalse(LLMRoutingLog.objects.exists())
        self.invoke.assert_not_awaited()

    def test_manual_destination_and_accuracy_save_to_database(self):
        self.invoke.return_value = self.response([])
        self.post(self.payload())
        log = LLMRoutingLog.objects.get()
        response = self.client.post(reverse("ROUTER:route_add", args=[log.pk]), {"destination_id": self.ap.pk, "reason": "Verified invoice issuer"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(log.routes.get().confidence, None)
        response = self.client.post(reverse("ROUTER:log_accuracy", args=[log.pk]), {"accurate": True, "revision": log.updated_at.isoformat()}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        log.refresh_from_db()
        self.assertTrue(log.user_selected_accurate)
