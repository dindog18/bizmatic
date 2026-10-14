"""Form handling shared by the document CRUD routes."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from ..forms import AccuracyForm, DocumentEditForm, MarkdownForm, ReviewForm
from ..models import LLMExtractionLog
from . import pages, records
from .uploads import process_batch_rerun, process_document_rerun


def _form_error(form, error: ValidationError) -> int:
    form.add_error(None, error)
    return 409 if error.code == "conflict" else 400


def rerun_response(request: HttpRequest, *, document_no: int | None = None,
                   batch_no: int | None = None) -> HttpResponse:
    """Run the shared upload pipeline and surface failures with saved history."""
    document_run = document_no is not None
    route = "document_detail" if document_run else "batch_detail"
    identifier = document_no if document_run else batch_no
    # Resolve the target before catching processing errors so unknown IDs stay 404.
    def context() -> dict:
        if document_no is not None:
            return pages.document_detail_context(document_no)
        if batch_no is None:
            raise ValueError("A document or batch is required.")
        return pages.batch_detail_context(request.GET, batch_no)

    context()
    try:
        if document_no is not None:
            process_document_rerun(document_no)
        else:
            assert batch_no is not None
            process_batch_rerun(batch_no)
    except ValidationError as error:
        message = "; ".join(error.messages)
        status = 409 if error.code == "conflict" else 400
    except Exception as error:
        message = f"Re-run failed: {str(error) or type(error).__name__}. Check the extraction history for saved results."
        status = 502
    else:
        messages.success(request, "Re-run completed. New extraction attempts were saved; review is pending.")
        return redirect(f"DOC_EXTRACTION:{route}", identifier)
    return render(request, f"document_extraction/{route}.html", {**context(), "action_error": message}, status=status)


def document_edit_response(request: HttpRequest, document_no: int) -> HttpResponse:
    document = records.get_document(document_no)
    form = DocumentEditForm(request.POST if request.method == "POST" else None, instance=document)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                records.update_document(document_no, form.cleaned_data)
            except ValidationError as error:
                status = _form_error(form, error)
            else:
                messages.success(request, "Document updated. Review is now pending.")
                return redirect("DOC_EXTRACTION:document_detail", document_no=document_no)
    return render(request, "document_extraction/record_form.html", {
        "page_title": "Edit document", "section": "documents", "document": document,
        "form": form, "submit_label": "Save document",
    }, status=status)


def extraction_edit_response(request: HttpRequest, document_no: int, log_no: int, model: records.LogModel) -> HttpResponse:
    log = records.get_extraction(document_no, log_no, model)
    form = MarkdownForm(request.POST if request.method == "POST" else None,
                        initial={"markdown_text": log.markdown_text or "", "revision": log.updated_at.isoformat()})
    form.fields["revision"].required = True
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                records.save_markdown(document_no, form.cleaned_data, model, log_no)
            except ValidationError as error:
                status = _form_error(form, error)
            else:
                messages.success(request, "Markdown saved. Changed content needs a new accuracy check and review.")
                route = "llm_extraction_detail" if model is LLMExtractionLog else "doc_extraction_detail"
                return redirect(f"DOC_EXTRACTION:{route}", document_no, log_no)
    context = pages.extraction_detail_context(document_no, log_no, model, edit_mode=True)
    return render(request, "document_extraction/extraction_detail.html", {**context, "form": form}, status=status)


def extraction_create_response(request: HttpRequest, document_no: int) -> HttpResponse:
    document = records.get_document(document_no)
    form = MarkdownForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            log = records.save_markdown(document_no, form.cleaned_data)
        except ValidationError as error:
            status = _form_error(form, error)
        else:
            messages.success(request, "Text extraction created. Review is now pending.")
            return redirect("DOC_EXTRACTION:doc_extraction_detail", document_no, log.pk)
    else:
        status = 400 if request.method == "POST" else 200
    return render(request, "document_extraction/record_form.html", {
        "page_title": "Add text extraction", "section": "documents", "document": document,
        "form": form, "submit_label": "Create extraction", "show_original": True,
    }, status=status)


def review_response(request: HttpRequest, document_no: int) -> HttpResponse:
    context = pages.document_detail_context(document_no)
    form = ReviewForm(request.POST)
    error_message, status = "Choose a valid review status.", 400
    if form.is_valid():
        try:
            records.set_review(document_no, form.cleaned_data["review_status"])
        except ValidationError as error:
            error_message = "; ".join(error.messages)
            status = 409 if error.code == "conflict" else 400
        else:
            messages.success(request, f"Document review set to {form.cleaned_data['review_status']}.")
            return redirect("DOC_EXTRACTION:document_detail", document_no=document_no)
    return render(request, "document_extraction/document_detail.html",
                  {**context, "action_error": error_message}, status=status)


def accuracy_response(request: HttpRequest, document_no: int, log_no: int, model: records.LogModel) -> HttpResponse:
    records.get_extraction(document_no, log_no, model)
    form = AccuracyForm(request.POST)
    error_message = "Choose a valid accuracy value."
    status = 400
    if form.is_valid():
        try:
            records.set_accuracy(document_no, log_no, model, form.cleaned_data["accurate"])
        except ValidationError as error:
            error_message = "; ".join(error.messages)
            status = 409 if error.code == "conflict" else 400
        else:
            messages.success(request, "Accuracy updated. Changes require a new review.")
            return redirect("DOC_EXTRACTION:document_detail", document_no=document_no)
    return render(request, "document_extraction/document_detail.html",
                  {**pages.document_detail_context(document_no), "action_error": error_message}, status=status)


def delete_response(request: HttpRequest, document_no: int, model: records.LogModel | None = None,
                    log_no: int | None = None) -> HttpResponse:
    document = records.get_document(document_no)
    log = records.get_extraction(document_no, log_no, model) if model else None
    title = f"Delete {'LLM' if model is LLMExtractionLog else 'text'} extraction #{log_no}" if model else f"Delete document #{document_no}"
    error_message = "Confirm deletion before continuing." if request.method == "POST" else ""
    status = 400 if request.method == "POST" else 200
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        try:
            records.delete_record(document_no, model, log_no)
        except ValidationError as error:
            error_message = "; ".join(error.messages)
            status = 409 if error.code == "conflict" else 400
        else:
            messages.success(request, "Extraction deleted. Review is now pending." if model else "Document and related logs deleted. The original file was kept on disk.")
            return redirect("DOC_EXTRACTION:document_detail", document_no=document_no) if model else redirect("DOC_EXTRACTION:document_list")
    return render(request, "document_extraction/record_delete.html", {
        "page_title": title, "section": "documents", "document": document, "log": log,
        "deleting_document": model is None,
        "cancel_url": reverse("DOC_EXTRACTION:document_detail", args=[document_no]),
        "action_error": error_message,
    }, status=status)
