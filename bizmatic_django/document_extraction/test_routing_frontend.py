"""Routing confirmation receives saved review states without mutating records."""

from django.test import TestCase
from django.urls import reverse

from .models import Batch, Document


class RoutingFrontendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.batch = Batch.objects.create()
        cls.pending = Document.objects.create(
            fk_batch_no=cls.batch, file_name="Pending.pdf", document_type="pdf",
            storage_path="pending.pdf", processing_status="completed", review_status="pending",
        )
        cls.rejected = Document.objects.create(
            fk_batch_no=cls.batch, file_name="Rejected.pdf", document_type="pdf",
            storage_path="rejected.pdf", processing_status="completed", review_status="rejected",
        )
        for index in range(25):
            cls.approved = Document.objects.create(
                fk_batch_no=cls.batch, file_name=f"Approved {index}.pdf", document_type="pdf",
                storage_path=f"approved-{index}.pdf", processing_status="completed",
                review_status="approved",
            )

    def test_batch_confirmation_includes_unapproved_documents_beyond_first_page(self):
        response = self.client.get(reverse("DOC_EXTRACTION:batch_detail", args=[self.batch.pk]))
        self.assertEqual(len(response.context["documents"]), 25)
        payload = response.context["routing_documents"]
        self.assertEqual(len(payload), 27)
        states = {doc["id"]: doc["review_status"] for doc in payload}
        self.assertEqual(states[self.pending.pk], "pending")
        self.assertEqual(states[self.rejected.pk], "rejected")
        self.assertContains(response, 'data-routing-trigger="batch"')
        self.assertContains(response, 'id="document-routing-dialog"')

    def test_document_and_selection_use_saved_reviews(self):
        for document in (self.pending, self.rejected, self.approved):
            saved_review = document.review_status
            response = self.client.get(reverse("DOC_EXTRACTION:document_detail", args=[document.pk]))
            self.assertEqual(response.context["routing_documents"], [{
                "id": document.pk, "name": document.file_name,
                "review_status": document.review_status,
                "revision": document.updated_at.isoformat(),
            }])
            self.assertContains(response, 'data-routing-trigger="document"')
            document.refresh_from_db()
            self.assertEqual(document.review_status, saved_review)
        listing = self.client.get(reverse("DOC_EXTRACTION:document_list"))
        self.assertEqual(len(listing.context["routing_documents"]), 25)
        self.assertContains(listing, "data-routing-select-all")
        self.assertContains(listing, 'data-routing-trigger="selected"')
