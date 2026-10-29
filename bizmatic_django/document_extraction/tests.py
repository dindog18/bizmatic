from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .models import Batch, Document, DocExtractionLog, LLMExtractionLog
from .templatetags.extraction_markdown import extraction_markdown


class ReadOnlyPagesTests(TestCase):
    """Fixtures are written only to Django's isolated test database."""

    @classmethod
    def setUpTestData(cls):
        cls.batch = Batch.objects.create()
        cls.empty_batch = Batch.objects.create()
        cls.document = Document.objects.create(
            fk_batch_no=cls.batch, file_name="Invoice & receipt.pdf", document_type="Invoice",
            mime_type="application/pdf", storage_path="invoices/receipt.pdf",
            processing_status="completed", review_status="approved",
        )
        cls.other = Document.objects.create(
            file_name="Scan.jpg", document_type="Receipt", storage_path="scans/scan.jpg",
            processing_status="failed",
        )
        cls.text = DocExtractionLog.objects.create(
            fk_document_no=cls.document, markdown_text="# Invoice\n\n**Total: 100**",
            user_selected_accurate=True,
        )
        cls.llm = LLMExtractionLog.objects.create(
            fk_document_no=cls.document, status="failed", error_message="Provider timed out.",
        )

    def paths(self):
        return ["/", "/documents/", "/documents/upload/", "/batches/",
                f"/batches/{self.batch.pk}/", f"/documents/{self.document.pk}/",
                f"/documents/{self.document.pk}/docextract/{self.text.pk}/",
                f"/documents/{self.document.pk}/llmextract/{self.llm.pk}/",
                f"/documents/{self.document.pk}/llmextract/{self.llm.pk}/edit/",
                f"/documents/{self.document.pk}/docextract/{self.text.pk}/edit/",
                f"/documents/{self.document.pk}/edit/",
                f"/documents/{self.document.pk}/delete/",
                f"/documents/{self.document.pk}/docextract/new/",
                f"/documents/{self.document.pk}/docextract/{self.text.pk}/delete/",
                f"/documents/{self.document.pk}/llmextract/{self.llm.pk}/delete/"]

    def test_requests_only_read_the_database(self):
        # Fail immediately if any view or middleware issues a write query.
        def only_reads(execute, sql, params, many, context):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(only_reads):
            for path in self.paths():
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path, follow=True).status_code, 200)
                    self.assertIn(self.client.head(path).status_code, (200, 302))
            self.assertEqual(self.client.get('/documents/', {'q': 'Invoice', 'status': 'completed'}).status_code, 200)

    def test_write_methods_are_rejected(self):
        for path in self.paths()[1:]:
            for method in ('post', 'put', 'patch', 'delete'):
                if method == 'post' and (path == '/documents/upload/' or path.endswith(('/edit/', '/delete/', '/new/'))):
                    continue  # CRUD POST routes have their own persistence tests.
                with self.subTest(path=path, method=method):
                    self.assertEqual(getattr(self.client, method)(path).status_code, 405)

    def test_real_document_and_single_result_render(self):
        response = self.client.get(f'/documents/{self.document.pk}/')
        self.assertContains(response, 'Invoice &amp; receipt.pdf')
        self.assertContains(response, '<h1>Invoice</h1>', html=True)
        self.assertContains(response, 'Selected as accurate')
        self.assertContains(response, 'Re-Run</button>')
        self.assertNotContains(response, 'Sample data')
        self.assertNotContains(response, 'Provider timed out.')
        self.assertContains(self.client.get(f'/documents/{self.document.pk}/llmextract/{self.llm.pk}/'), 'Provider timed out.')
        self.assertEqual(self.client.get(f'/documents/{self.document.pk}/logs/').status_code, 404)
        self.assertContains(response, 'LLM extractions')

    def test_multiple_and_empty_results(self):
        newest = DocExtractionLog.objects.create(fk_document_no=self.document, markdown_text='New attempt')
        response = self.client.get(f'/documents/{self.document.pk}/')
        self.assertEqual([log.pk for log in response.context['text_logs']], [newest.pk, self.text.pk])
        self.assertContains(response, f'/docextract/{newest.pk}/')
        self.assertNotContains(response, '<h1>Invoice</h1>')
        empty = self.client.get(f'/documents/{self.other.pk}/')
        self.assertNotContains(empty, 'Text extractions')
        self.assertNotContains(empty, 'LLM extractions')

    def test_editor_escapes_source_and_validates_submission(self):
        self.llm.markdown_text = '# Receipt\n\n</textarea><script>alert(1)</script>'
        self.llm.save()
        path = f'/documents/{self.document.pk}/llmextract/{self.llm.pk}/edit/'
        response = self.client.get(path)
        self.assertContains(response, 'id="markdown-editor"')
        self.assertContains(response, 'Save Markdown')
        self.assertContains(response, '&lt;/textarea&gt;&lt;script&gt;')
        self.assertEqual(self.client.post(path, {'markdown_text': 'Changed'}).status_code, 400)
        self.llm.refresh_from_db()
        self.assertTrue(self.llm.markdown_text.startswith('# Receipt'))

    def test_original_file_uses_saved_path(self):
        with TemporaryDirectory() as directory:
            stored = Path(directory) / 'stored.txt'
            stored.write_bytes(b'Original stored content')
            self.document.storage_path = str(stored)
            self.document.file_name = 'Original.txt'
            self.document.save()
            path = f'/documents/{self.document.pk}/original/'
            response = self.client.get(path, {'path': '/etc/passwd'})
            self.assertEqual(b''.join(response.streaming_content), b'Original stored content')
            # Consuming the test client streaming iterator closes the response
            # with connection-cleanup signals suspended for TestCase transactions.
            self.assertEqual(response['Content-Type'], 'text/plain')
            download = self.client.get(path, {'download': '1'})
            self.assertIn('attachment', download['Content-Disposition'])
            self.assertEqual(b''.join(download.streaming_content), b'Original stored content')
            head = self.client.head(path)
            self.assertEqual(head.status_code, 200)
            self.assertEqual(b''.join(head.streaming_content), b'')
            self.assertEqual(self.client.post(path).status_code, 405)
            stored.unlink()
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get('/documents/99999/original/').status_code, 404)
        detail = self.client.get(f'/documents/{self.document.pk}/')
        self.assertContains(detail, f'data-file-url="{path}"')
        self.assertNotContains(detail, 'Choose the original file')

    def test_search_and_each_filter(self):
        cases = [({'q': 'invoice'}, [self.document.pk]),
                 ({'q': f'#{self.other.pk}'}, [self.other.pk]),
                 ({'type': 'Invoice'}, [self.document.pk]),
                 ({'batch': str(self.batch.pk)}, [self.document.pk]),
                 ({'batch': 'unassigned'}, [self.other.pk]),
                 ({'status': 'failed'}, [self.other.pk]),
                 ({'review': 'approved'}, [self.document.pk]),
                 ({'q': 'Invoice', 'type': 'Invoice', 'batch': str(self.batch.pk), 'status': 'completed', 'review': 'approved'}, [self.document.pk]),
                 ({'q': 'Invoice', 'status': 'failed'}, []),
                 ({'batch': 'invalid'}, []), ({'batch': '9' * 100}, []),
                 ({'q': '9' * 100}, [])]
        for params, expected in cases:
            with self.subTest(params=params):
                response = self.client.get('/documents/', params)
                self.assertEqual([doc.pk for doc in response.context['documents']], expected)
                self.assertEqual(sum(item['count'] for item in response.context['summary']), len(expected))

    def test_pagination_preserves_filters(self):
        Document.objects.bulk_create([
            Document(file_name=f'paged {i}.pdf', document_type='Invoice', storage_path=f'files/{i}')
            for i in range(26)
        ])
        response = self.client.get('/documents/', {'q': 'paged', 'type': 'Invoice'})
        self.assertEqual(len(response.context['documents']), 25)
        self.assertContains(response, 'q=paged&amp;type=Invoice&amp;page=2')
        response = self.client.get('/documents/', {'q': 'paged', 'page': 2})
        self.assertEqual(len(response.context['documents']), 1)
        self.assertEqual(self.client.get('/documents/', {'page': 'bad'}).status_code, 200)

    def test_batch_counts_and_membership(self):
        response = self.client.get(f'/batches/{self.batch.pk}/')
        self.assertEqual(response.context['batch'].count, 1)
        self.assertEqual(response.context['batch'].progress, 100)
        self.assertEqual([doc.pk for doc in response.context['documents']], [self.document.pk])
        response = self.client.get(f'/batches/{self.empty_batch.pk}/')
        self.assertEqual(response.context['batch'].progress, 0)
        self.assertContains(response, 'No documents found.')

    def test_empty_database_shows_empty_states(self):
        Document.objects.all().delete()
        Batch.objects.all().delete()
        self.assertContains(self.client.get('/documents/'), 'No documents found.')
        self.assertContains(self.client.get('/batches/'), 'No batches found.')

    def test_missing_records_and_mismatched_logs_return_404(self):
        for path in [f'/documents/{self.other.pk}/docextract/{self.text.pk}/',
                     f'/documents/{self.other.pk}/llmextract/{self.llm.pk}/',
                     '/documents/99999/', '/documents/99999/logs/', '/batches/99999/',
                     f'/documents/{self.document.pk}/docextract/99999/',
                     f'/documents/{self.document.pk}/llmextract/99999/']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_home_opens_documents(self):
        self.assertRedirects(self.client.get('/'), reverse('DOC_EXTRACTION:document_list'))

    def test_markdown_is_safe(self):
        rendered = extraction_markdown('# Receipt\n\n**Total**\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![image](https://example.com/pixel.png)')
        self.assertIn('<strong>Total</strong>', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertNotIn('<img', rendered)
