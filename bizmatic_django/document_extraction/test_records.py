"""Exercise CRUD only against Django's isolated database and temporary files."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import Client, TestCase

from .models import Batch, Document, DocExtractionLog, LLMExtractionLog


class DocumentCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.batch = Batch.objects.create()
        cls.document = Document.objects.create(file_name="Receipt.pdf", document_type="Receipt",
                                              storage_path="files/Receipt.pdf", processing_status="completed")
        cls.other = Document.objects.create(file_name="Other.jpg", document_type="image", storage_path="Other.jpg")
        cls.text = DocExtractionLog.objects.create(fk_document_no=cls.document, markdown_text="# Text")
        cls.llm = LLMExtractionLog.objects.create(fk_document_no=cls.document, markdown_text="# LLM",
                                                  provider="openai", model_name="gpt-4o", status="completed",
                                                  input_tokens=10, output_tokens=20, processing_time_ms=30)

    def url(self, suffix=""):
        return f"/documents/{self.document.pk}/{suffix}"

    def test_review_states_persist_and_invalid_status_does_not(self):
        for value in ("approved", "rejected", "pending"):
            response = self.client.post(self.url('review/'), {'review_status': value}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.document.refresh_from_db()
            self.assertEqual(self.document.review_status, value)
        self.assertEqual(self.client.post(self.url('review/'), {'review_status': 'unknown'}).status_code, 400)
        self.assertEqual(self.client.get(self.url('review/')).status_code, 405)

    def test_accuracy_is_independent_per_log_and_resets_review(self):
        for prefix, log in (("docextract", self.text), ("llmextract", self.llm)):
            self.client.post(self.url('review/'), {'review_status': 'approved'})
            response = self.client.post(self.url(f'{prefix}/{log.pk}/accuracy/'), {'accurate': '1'})
            self.assertEqual(response.status_code, 302)
            log.refresh_from_db(); self.document.refresh_from_db()
            self.assertTrue(log.user_selected_accurate)
            self.assertEqual(self.document.review_status, 'pending')
        self.text.refresh_from_db()
        self.assertTrue(self.text.user_selected_accurate)
        self.assertEqual(self.client.post(self.url(f'llmextract/{self.llm.pk}/accuracy/'), {'accurate': '0'}).status_code, 302)
        self.llm.refresh_from_db()
        self.assertFalse(self.llm.user_selected_accurate)
        self.assertEqual(self.client.post(self.url(f'docextract/{self.text.pk}/accuracy/'), {'accurate': 'invalid'}).status_code, 400)

    def test_empty_results_cannot_be_marked_accurate(self):
        self.llm.markdown_text = '   '; self.llm.save()
        response = self.client.post(self.url(f'llmextract/{self.llm.pk}/accuracy/'), {'accurate': '1'})
        self.assertEqual(response.status_code, 400)
        self.llm.refresh_from_db()
        self.assertFalse(self.llm.user_selected_accurate)

    def test_markdown_save_persists_and_invalidates_prior_review(self):
        for prefix, log in (("docextract", self.text), ("llmextract", self.llm)):
            self.client.post(self.url(f'{prefix}/{log.pk}/accuracy/'), {'accurate': '1'})
            self.client.post(self.url('review/'), {'review_status': 'approved'})
            log.refresh_from_db()
            source = '# Corrected\n\n| Item | Total |\n| --- | --- |\n| Receipt | 100 |'
            response = self.client.post(self.url(f'{prefix}/{log.pk}/edit/'),
                                        {'markdown_text': source, 'revision': log.updated_at.isoformat()}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Markdown saved')
            log.refresh_from_db(); self.document.refresh_from_db()
            self.assertEqual(log.markdown_text, source)
            self.assertFalse(log.user_selected_accurate)
            self.assertEqual(self.document.review_status, 'pending')
        self.llm.refresh_from_db()
        self.assertEqual((self.llm.provider, self.llm.model_name, self.llm.input_tokens,
                          self.llm.output_tokens, self.llm.processing_time_ms, self.llm.status),
                         ('openai', 'gpt-4o', 10, 20, 30, 'completed'))

    def test_stale_and_empty_edit_cannot_overwrite_newer_content(self):
        path = self.url(f'llmextract/{self.llm.pk}/edit/')
        revision = self.llm.updated_at.isoformat()
        self.client.post(path, {'markdown_text': '# First edit', 'revision': revision})
        response = self.client.post(path, {'markdown_text': '# Stale edit', 'revision': revision})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'changed while you were editing', status_code=409)
        self.llm.refresh_from_db()
        self.assertEqual(self.llm.markdown_text, '# First edit')
        self.assertEqual(self.client.post(path, {'markdown_text': '   ', 'revision': self.llm.updated_at.isoformat()}).status_code, 400)

    def test_document_edit_only_changes_allowed_fields(self):
        response = self.client.post(self.url('edit/'), {'file_name': 'Renamed.pdf', 'document_type': 'Invoice',
                                   'fk_batch_no': self.batch.pk, 'revision': self.document.updated_at.isoformat(),
                                   'storage_path': '/etc/passwd', 'processing_status': 'failed'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.document.refresh_from_db()
        self.assertEqual((self.document.file_name, self.document.document_type, self.document.fk_batch_no_id),
                         ('Renamed.pdf', 'Invoice', self.batch.pk))
        self.assertEqual(self.document.storage_path, 'files/Receipt.pdf')
        self.assertEqual(self.document.processing_status, 'completed')
        for name in ('Renamed.jpg', '../Receipt.pdf'):
            self.assertEqual(self.client.post(self.url('edit/'), {'file_name': name, 'document_type': 'Invoice',
                             'fk_batch_no': '', 'revision': self.document.updated_at.isoformat()}).status_code, 400)

    def test_create_manual_text_extraction(self):
        before = DocExtractionLog.objects.count()
        response = self.client.post(self.url('docextract/new/'), {'markdown_text': '# Manual correction'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DocExtractionLog.objects.count(), before + 1)
        self.assertEqual(DocExtractionLog.objects.latest('pk').fk_document_no_id, self.document.pk)
        self.assertEqual(LLMExtractionLog.objects.count(), 1)
        self.assertEqual(self.client.post(self.url('docextract/new/'), {'markdown_text': ''}).status_code, 400)

    def test_log_ownership_on_all_mutation_routes(self):
        for prefix, log in (("docextract", self.text), ("llmextract", self.llm)):
            for suffix in ('edit/', 'accuracy/', 'delete/'):
                path = f'/documents/{self.other.pk}/{prefix}/{log.pk}/{suffix}'
                self.assertEqual(self.client.post(path, {'accurate': '1', 'confirm': 'yes'}).status_code, 404)
        self.assertEqual(DocExtractionLog.objects.count(), 1)
        self.assertEqual(LLMExtractionLog.objects.count(), 1)

    def test_delete_extractions_requires_confirmation_and_keeps_document(self):
        for prefix, log in (("docextract", self.text), ("llmextract", self.llm)):
            path = self.url(f'{prefix}/{log.pk}/delete/')
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(self.client.post(path).status_code, 400)
            self.assertTrue(type(log).objects.filter(pk=log.pk).exists())
            self.assertEqual(self.client.post(path, {'confirm': 'yes'}).status_code, 302)
            self.assertFalse(type(log).objects.filter(pk=log.pk).exists())
        self.assertTrue(Document.objects.filter(pk=self.document.pk).exists())

    def test_document_delete_cascades_logs_and_preserves_original(self):
        with TemporaryDirectory() as directory:
            original = Path(directory) / 'Receipt.pdf'; original.write_bytes(b'Original')
            self.document.storage_path = str(original); self.document.save()
            self.assertEqual(self.client.get(self.url('delete/')).status_code, 200)
            self.assertEqual(self.client.post(self.url('delete/'), {'confirm': 'yes'}).status_code, 302)
            self.assertFalse(Document.objects.filter(pk=self.document.pk).exists())
            self.assertEqual(DocExtractionLog.objects.count(), 0)
            self.assertEqual(LLMExtractionLog.objects.count(), 0)
            self.assertEqual(original.read_bytes(), b'Original')

    def test_csrf_required_for_every_write_action(self):
        client = Client(enforce_csrf_checks=True)
        for suffix in ('review/', 'edit/', 'delete/', 'docextract/new/',
                       f'llmextract/{self.llm.pk}/accuracy/', f'llmextract/{self.llm.pk}/edit/',
                       f'llmextract/{self.llm.pk}/delete/'):
            self.assertEqual(client.post(self.url(suffix), {'confirm': 'yes'}).status_code, 403)

    def test_processing_records_cannot_be_changed_before_callbacks_finish(self):
        for processing_status in ('queued', 'processing'):
            self.document.processing_status = processing_status
            self.document.save()
            actions = [('review/', {'review_status': 'approved'}),
                       ('delete/', {'confirm': 'yes'}),
                       ('docextract/new/', {'markdown_text': '# Premature correction'}),
                       ('edit/', {'file_name': 'Renamed.pdf', 'document_type': 'Receipt',
                                  'fk_batch_no': '', 'revision': self.document.updated_at.isoformat()}),
                       (f'llmextract/{self.llm.pk}/edit/', {'markdown_text': '# Changed', 'revision': self.llm.updated_at.isoformat()}),
                       (f'llmextract/{self.llm.pk}/accuracy/', {'accurate': '1'}),
                       (f'docextract/{self.text.pk}/delete/', {'confirm': 'yes'})]
            for suffix, data in actions:
                with self.subTest(status=processing_status, suffix=suffix):
                    response = self.client.post(self.url(suffix), data)
                    self.assertEqual(response.status_code, 409)
                    self.assertContains(response, 'Wait for document processing', status_code=409)
            self.document.refresh_from_db(); self.llm.refresh_from_db()
            self.assertEqual(self.document.file_name, 'Receipt.pdf')
            self.assertEqual(self.llm.markdown_text, '# LLM')
            self.assertEqual(DocExtractionLog.objects.count(), 1)
