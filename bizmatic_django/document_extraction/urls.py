from django.urls import path
from django.views.generic.base import RedirectView
from . import views

app_name = "DOC_EXTRACTION"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="DOC_EXTRACTION:document_list", permanent=False), name="home"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path(
        "documents/<int:document_no>/",
        views.document_detail,
        name="document_detail",
    ),
    path("batches/", views.batch_list, name="batch_list"),
    path("batches/<int:batch_no>/rerun/", views.batch_rerun, name="batch_rerun"),
    path("documents/<int:document_no>/rerun/", views.document_rerun, name="document_rerun"),
    path("documents/<int:document_no>/original/", views.document_original, name="document_original"),
    path("documents/<int:document_no>/edit/", views.document_edit, name="document_edit"),
    path("documents/<int:document_no>/delete/", views.document_delete, name="document_delete"),
    path("documents/<int:document_no>/review/", views.document_review, name="document_review"),
    path("documents/<int:document_no>/docextract/new/", views.doc_extraction_create, name="doc_extraction_create"),
    path("documents/<int:document_no>/docextract/<int:doc_log_no>/", views.doc_extraction_detail, name="doc_extraction_detail"),
    path("documents/<int:document_no>/llmextract/<int:llm_log_no>/", views.llm_extraction_detail, name="llm_extraction_detail"),
    path("documents/<int:document_no>/llmextract/<int:llm_log_no>/edit/", views.llm_extraction_edit, name="llm_extraction_edit"),
    path("documents/<int:document_no>/docextract/<int:doc_log_no>/edit/", views.doc_extraction_edit, name="doc_extraction_edit"),
    path("documents/<int:document_no>/docextract/<int:doc_log_no>/accuracy/", views.doc_extraction_accuracy, name="doc_extraction_accuracy"),
    path("documents/<int:document_no>/llmextract/<int:llm_log_no>/accuracy/", views.llm_extraction_accuracy, name="llm_extraction_accuracy"),
    path("documents/<int:document_no>/docextract/<int:doc_log_no>/delete/", views.doc_extraction_delete, name="doc_extraction_delete"),
    path("documents/<int:document_no>/llmextract/<int:llm_log_no>/delete/", views.llm_extraction_delete, name="llm_extraction_delete"),
    path("batches/<int:batch_no>/", views.batch_detail, name="batch_detail"),
]
