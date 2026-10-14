"""Upload integration checks use isolated databases, temporary files and mocked APIs."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from .models import Batch, Document, DocExtractionLog, LLMExtractionLog
from .services import llm


class DocumentUploadTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = patch.dict(os.environ, {
            "LOCAL_FILE_STORAGE_PATH": self.directory.name,
            "DOC_EXTRACTION_MAX_CONCURRENCY": "3",
            "DOC_EXTRACTION_LLM_PROVIDER": "openai,ollama",
            "DOC_EXTRACTION_OPENAI_API_KEY": "test-key",
            "DOC_EXTRACTION_OPENAI_MODEL": "gpt-4o",
            "DOC_EXTRACTION_OLLAMA_MODEL": "qwen3-vl",
        })
        config.start()
        self.addCleanup(config.stop)

    def image(self, name="receipt.png"):
        return SimpleUploadedFile(name, b"test image bytes", content_type="image/png")

    async def response(self, url, payload, headers):
        await asyncio.sleep(0.005)
        if "/api/chat" in url:
            return {"model": "qwen3-vl", "message": {"content": "Local receipt"}, "done_reason": "stop", "prompt_eval_count": 11, "eval_count": 7}
        return {"model": "gpt-4o", "choices": [{"message": {"content": "Cloud receipt"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 8}}

    def test_upload_saves_batch_documents_and_both_log_types(self):
        previous = Batch.objects.create()
        files = [self.image(), SimpleUploadedFile("notes.txt", b"Notes text", content_type="text/plain")]
        with patch.object(llm, "_post", side_effect=self.response):
            response = self.client.post("/documents/upload/", {"files": files})
        batch = Batch.objects.order_by("-batch_no").first()
        self.assertEqual(batch.batch_no, previous.batch_no + 1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/batches/{batch.batch_no}/")
        documents = list(Document.objects.filter(fk_batch_no=batch).order_by("document_no"))
        self.assertEqual([document.file_name for document in documents], ["receipt.png", "notes.txt"])
        self.assertTrue(all(document.processing_status == "completed" for document in documents))
        self.assertTrue(all(document.review_status == "pending" for document in documents))
        self.assertTrue(all(Path(document.storage_path).is_file() for document in documents))
        log = LLMExtractionLog.objects.get(provider="openai")
        self.assertEqual((log.model_name, log.markdown_text, log.input_tokens, log.output_tokens), ("gpt-4o", "Cloud receipt", 12, 8))
        self.assertEqual(log.status, "completed")
        self.assertGreaterEqual(log.processing_time_ms, 0)
        self.assertFalse(log.user_selected_accurate)
        self.assertEqual(LLMExtractionLog.objects.get(provider="ollama").input_tokens, 11)
        text = DocExtractionLog.objects.get()
        self.assertEqual(text.markdown_text, "Notes text")
        self.assertEqual(text.fk_document_no, documents[1])
        self.assertIsNone(text.error_message)

    def test_missing_or_empty_upload_returns_errors_without_a_batch(self):
        for data in [{}, {"files": [SimpleUploadedFile("empty.txt", b"")]}]:
            response = self.client.post("/documents/upload/", data)
            self.assertEqual(response.status_code, 400)
            self.assertIn("files", response.json()["errors"])
        self.assertEqual(Batch.objects.count(), 0)

    def test_failed_provider_is_logged_and_success_is_retained(self):
        async def invoke(url, payload, headers):
            if "/api/chat" in url:
                await asyncio.sleep(0.025)
                raise RuntimeError("Provider timed out")
            return await self.response(url, payload, headers)
        with patch.object(llm, "_post", side_effect=invoke):
            with self.assertRaisesRegex(RuntimeError, "Provider timed out"):
                self.client.post("/documents/upload/", {"files": [self.image()]})
        self.assertEqual(Document.objects.get().processing_status, "failed")
        successful = LLMExtractionLog.objects.get(provider="openai")
        failed = LLMExtractionLog.objects.get(provider="ollama")
        self.assertEqual(successful.status, "completed")
        self.assertEqual(successful.markdown_text, "Cloud receipt")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_message, "Provider timed out")

    def test_document_failure_is_logged_and_raised(self):
        with self.assertRaises(ValueError):
            self.client.post("/documents/upload/", {"files": [SimpleUploadedFile("legacy.doc", b"legacy", content_type="application/msword")]})
        self.assertEqual(Document.objects.get().processing_status, "failed")
        self.assertIn("Legacy .doc", DocExtractionLog.objects.get().error_message)

    def test_provider_limit_is_shared_across_batch(self):
        active = peak = 0
        async def invoke(url, payload, headers):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                return await self.response(url, payload, headers)
            finally:
                active -= 1
        with patch.object(llm, "_post", side_effect=invoke):
            self.client.post("/documents/upload/", {"files": [self.image(f"{i}.png") for i in range(8)]})
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 3)
        self.assertEqual(LLMExtractionLog.objects.filter(status="completed").count(), 16)

    def test_cancelled_work_does_not_leave_queued_or_processing_rows(self):
        first = True

        async def invoke(url, payload, headers):
            nonlocal first
            if first:
                first = False
                await asyncio.sleep(0.005)
                raise RuntimeError("First provider failed")
            await asyncio.sleep(1)
            return await self.response(url, payload, headers)

        with patch.object(llm, "_post", side_effect=invoke):
            with self.assertRaisesRegex(RuntimeError, "First provider failed"):
                self.client.post("/documents/upload/", {"files": [self.image(f"{i}.png") for i in range(5)]})
        self.assertEqual(Document.objects.filter(processing_status="failed").count(), 5)
        self.assertEqual(LLMExtractionLog.objects.filter(status="failed").count(), 10)
        self.assertFalse(LLMExtractionLog.objects.filter(error_message__isnull=True).exists())

    def test_csrf_protection_remains_required(self):
        response = Client(enforce_csrf_checks=True).post("/documents/upload/", {"files": [self.image()]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Batch.objects.count(), 0)


class DocumentRerunTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = patch.dict(os.environ, {
            "DOC_EXTRACTION_MAX_CONCURRENCY": "3", "DOC_EXTRACTION_LLM_PROVIDER": "openai,ollama",
            "DOC_EXTRACTION_OPENAI_API_KEY": "test-key", "DOC_EXTRACTION_OPENAI_MODEL": "new-cloud-model",
            "DOC_EXTRACTION_OLLAMA_MODEL": "new-local-model",
        })
        config.start()
        self.addCleanup(config.stop)
        self.batch = Batch.objects.create()
        self.image = self.saved_document("receipt.png", b"synthetic image", "image/png", "image")
        self.text = self.saved_document("notes.txt", b"New notes", "text/plain", "text")
        self.old_llm = LLMExtractionLog.objects.create(fk_document_no=self.image, provider="openai", model_name="old-model",
                                                      status="completed", markdown_text="Old receipt", user_selected_accurate=True)
        self.old_text = DocExtractionLog.objects.create(fk_document_no=self.text, markdown_text="Old notes", user_selected_accurate=True)

    def saved_document(self, name, content, mime, kind):
        path = Path(self.directory.name) / name
        path.write_bytes(content)
        return Document.objects.create(fk_batch_no=self.batch, file_name=name, storage_path=str(path), mime_type=mime,
                                       document_type=kind, processing_status="completed", review_status="approved")

    async def response(self, url, payload, headers):
        await asyncio.sleep(0.005)
        if "/api/chat" in url:
            return {"model": payload["model"], "message": {"content": "New local receipt"}, "done_reason": "stop"}
        return {"model": payload["model"], "choices": [{"message": {"content": "New cloud receipt"}, "finish_reason": "stop"}]}

    def test_document_rerun_uses_saved_original_and_current_settings_preserving_history(self):
        original = Path(self.image.storage_path).read_bytes()
        with patch.object(llm, "_post", side_effect=self.response), patch("document_extraction.util.store_files_in_hdd") as store:
            response = self.client.post(f"/documents/{self.image.pk}/rerun/")
        self.assertRedirects(response, f"/documents/{self.image.pk}/")
        store.assert_not_called()
        self.assertEqual((Batch.objects.count(), Document.objects.count()), (1, 2))
        self.image.refresh_from_db()
        self.assertEqual((self.image.processing_status, self.image.review_status), ("completed", "pending"))
        self.old_llm.refresh_from_db()
        self.assertEqual((self.old_llm.markdown_text, self.old_llm.model_name, self.old_llm.user_selected_accurate), ("Old receipt", "old-model", True))
        new_logs = LLMExtractionLog.objects.exclude(pk=self.old_llm.pk)
        self.assertEqual(new_logs.count(), 2)
        self.assertEqual(new_logs.get(provider="openai").model_name, "new-cloud-model")
        self.assertTrue(all(log.status == "completed" and not log.user_selected_accurate for log in new_logs))
        self.assertEqual(Path(self.image.storage_path).read_bytes(), original)
        self.text.refresh_from_db()
        self.assertEqual(self.text.review_status, "approved")

    def test_batch_rerun_shares_upload_pipeline_for_mixed_files(self):
        # The editable document label must not determine which extraction log receives text.
        self.text.document_type = "Invoice"
        self.text.save()
        with patch.object(llm, "_post", side_effect=self.response):
            response = self.client.post(f"/batches/{self.batch.pk}/rerun/")
        self.assertRedirects(response, f"/batches/{self.batch.pk}/")
        self.assertEqual(LLMExtractionLog.objects.count(), 3)
        self.assertEqual(DocExtractionLog.objects.count(), 2)
        self.assertEqual(DocExtractionLog.objects.exclude(pk=self.old_text.pk).get().markdown_text, "New notes")
        self.old_text.refresh_from_db()
        self.assertEqual((self.old_text.markdown_text, self.old_text.user_selected_accurate), ("Old notes", True))
        self.text.refresh_from_db()
        self.assertEqual(self.text.document_type, "Invoice")
        self.assertFalse(Document.objects.exclude(processing_status="completed", review_status="pending").exists())

    def test_repeated_reruns_append_attempts_without_ambiguous_log_lookups(self):
        with patch.object(llm, "_post", side_effect=self.response):
            for _ in range(2):
                self.assertEqual(self.client.post(f"/batches/{self.batch.pk}/rerun/").status_code, 302)
        self.assertEqual((LLMExtractionLog.objects.count(), DocExtractionLog.objects.count()), (5, 3))

    def test_failed_rerun_keeps_successes_and_only_updates_new_attempts(self):
        historical = LLMExtractionLog.objects.create(fk_document_no=self.image, provider="ollama", status="queued")
        async def invoke(url, payload, headers):
            if "/api/chat" in url:
                await asyncio.sleep(0.03)
                raise RuntimeError("Local provider failed")
            return await self.response(url, payload, headers)
        with patch.object(llm, "_post", side_effect=invoke):
            response = self.client.post(f"/documents/{self.image.pk}/rerun/")
        self.assertContains(response, "Local provider failed", status_code=502)
        self.image.refresh_from_db()
        self.assertEqual(self.image.processing_status, "failed")
        historical.refresh_from_db()
        self.assertEqual(historical.status, "queued")
        new_logs = LLMExtractionLog.objects.exclude(pk__in=[self.old_llm.pk, historical.pk])
        self.assertEqual(new_logs.get(provider="openai").status, "completed")
        self.assertEqual(new_logs.get(provider="ollama").status, "failed")
        self.old_llm.refresh_from_db()
        self.assertEqual(self.old_llm.markdown_text, "Old receipt")

    def test_missing_original_or_active_document_prevents_entire_batch_rerun(self):
        for mode, expected_status in [("processing", 409), ("missing", 400)]:
            if mode == "processing":
                self.text.processing_status = "processing"
                self.text.save()
            else:
                self.text.processing_status = "completed"
                self.text.save()
                Path(self.text.storage_path).unlink()
            with patch.object(llm, "_post") as invoke:
                response = self.client.post(f"/batches/{self.batch.pk}/rerun/")
            self.assertEqual(response.status_code, expected_status)
            invoke.assert_not_called()
            self.assertEqual((LLMExtractionLog.objects.count(), DocExtractionLog.objects.count()), (1, 1))
            self.image.refresh_from_db()
            self.assertEqual((self.image.processing_status, self.image.review_status), ("completed", "approved"))

    def test_batch_rerun_processes_all_documents_beyond_displayed_page(self):
        for i in range(26):
            self.saved_document(f"{i}.txt", b"Notes", "text/plain", "text")
        with patch.object(llm, "_post", side_effect=self.response):
            self.assertEqual(self.client.post(f"/batches/{self.batch.pk}/rerun/").status_code, 302)
        self.assertEqual(DocExtractionLog.objects.count(), 28)
        self.assertEqual(Document.objects.filter(review_status="pending").count(), 28)

    def test_empty_batch_and_missing_targets_do_not_run(self):
        empty = Batch.objects.create()
        with patch.object(llm, "_post") as invoke:
            self.assertEqual(self.client.post(f"/batches/{empty.pk}/rerun/").status_code, 400)
            for path in ["/documents/999999/rerun/", "/batches/999999/rerun/"]:
                self.assertEqual(self.client.post(path).status_code, 404)
        invoke.assert_not_called()

    def test_unassigned_document_rerun_does_not_allocate_batch(self):
        self.text.fk_batch_no = None
        self.text.save()
        self.assertEqual(self.client.post(f"/documents/{self.text.pk}/rerun/").status_code, 302)
        self.text.refresh_from_db()
        self.assertIsNone(self.text.fk_batch_no_id)
        self.assertEqual(Batch.objects.count(), 1)

    def test_rerun_requires_csrf_and_post(self):
        for path in [f"/documents/{self.image.pk}/rerun/", f"/batches/{self.batch.pk}/rerun/"]:
            self.assertEqual(self.client.get(path).status_code, 405)
            self.assertEqual(Client(enforce_csrf_checks=True).post(path).status_code, 403)
        self.assertEqual((LLMExtractionLog.objects.count(), DocExtractionLog.objects.count()), (1, 1))
