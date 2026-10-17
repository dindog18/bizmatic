"""PostgreSQL connection and metadata workspace, accessible without login."""

from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe, require_http_methods

from .forms import DatabaseSourceForm
from .models import DatabaseSource, DatabaseTable, ExtractionRun
from .services import pages
from .services.extraction import delete_source, refresh_source
from .services.postgres import InspectionError, test_connection


def _render(request, template, context, status=200):
    return render(request, f"db_extraction/{template}.html", {"section": "databases", **context}, status=status)


def _credential_error(request):
    return _render(request, "error", {
        "page_title": "Credential key unavailable",
        "error_message": "The database credential key is unavailable or invalid. Ask an administrator to provision or restore the configured key.",
    }, status=503)


@require_safe
def source_list(request):
    query = request.GET.get("q", "").strip()
    sources = DatabaseSource.objects.defer("password")
    if query:
        sources = sources.filter(Q(name__icontains=query) | Q(host__icontains=query) | Q(database_name__icontains=query))
    state = request.GET.get("state", "")
    if state in {"enabled", "disabled"}:
        sources = sources.filter(enabled=state == "enabled")
    return _render(request, "source_list", {
        "page_title": "Database connections", "query": query, "state": state,
        "source_count": DatabaseSource.objects.count(), "enabled_count": DatabaseSource.objects.filter(enabled=True).count(),
        "run_count": ExtractionRun.objects.filter(status="completed").count(), **pages.paginate(request, sources),
    })


@require_http_methods(["GET", "HEAD", "POST"])
def source_form(request, source_id=None):
    try:
        source = get_object_or_404(DatabaseSource, pk=source_id) if source_id is not None else None
        form = DatabaseSourceForm(request.POST if request.method == "POST" else None, instance=source)
    except ImproperlyConfigured:
        return _credential_error(request)
    valid = form.is_valid() if request.method == "POST" else False
    if request.method == "POST" and request.POST.get("intent") == "test" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if valid:
            result = form.connection_result or {}
            return JsonResponse({"message": f"Connection verified: PostgreSQL {result['server_version']}; {result['schema_count']} accessible schemas. Settings have not been saved."})
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
    if valid:
        if request.POST.get("intent") == "test":
            result = form.connection_result or {}
            messages.success(request, f"Connection verified: PostgreSQL {result['server_version']}; {result['schema_count']} accessible schemas. Settings have not been saved.")
        else:
            try:
                with transaction.atomic():
                    saved = form.save()
            except ImproperlyConfigured:
                return _credential_error(request)
            messages.success(request, "Connection tested and saved. Refresh its schema to capture metadata.")
            return redirect("DB_EXTRACTION:source_detail", source_id=saved.pk)
    return _render(request, "source_form", {
        "page_title": "Edit database connection" if source else "Add database connection",
        "source": source, "form": form,
    })


@require_safe
def source_detail(request, source_id):
    source = get_object_or_404(DatabaseSource.objects.defer("password"), pk=source_id)
    run = source.extraction_runs.filter(status="completed").first()
    query = request.GET.get("q", "").strip()
    schema = request.GET.get("schema", "")
    return _render(request, "source_detail", {
        "page_title": source.name, "source": source, "snapshot": run,
        "latest_attempt": source.extraction_runs.first(), "counts": pages.snapshot_counts(run),
        "query": query, "schema_filter": schema, "schemas": run.schemas.all() if run else [],
        **pages.paginate(request, pages.snapshot_tables(run, query, schema) if run else DatabaseTable.objects.none()),
    })


@require_POST
def source_test(request, source_id):
    try:
        source = get_object_or_404(DatabaseSource, pk=source_id)
        result = test_connection(source)
        messages.success(request, f"Connection verified: PostgreSQL {result['server_version']}; {result['schema_count']} accessible schemas.")
    except ImproperlyConfigured:
        return _credential_error(request)
    except InspectionError as error:
        messages.error(request, str(error))
    return redirect("DB_EXTRACTION:source_detail", source_id=source_id)


@require_POST
def source_refresh(request, source_id):
    get_object_or_404(DatabaseSource.objects.only("pk"), pk=source_id)
    try:
        run = refresh_source(source_id)
    except ImproperlyConfigured:
        return _credential_error(request)
    except InspectionError as error:
        messages.error(request, str(error))
        return redirect("DB_EXTRACTION:source_detail", source_id=source_id)
    if run.status == "completed":
        messages.success(request, "Schema refreshed. A new metadata snapshot has been saved.")
    else:
        messages.error(request, run.error_message)
    return redirect("DB_EXTRACTION:run_detail", source_id=source_id, run_id=run.pk)


@require_http_methods(["GET", "HEAD", "POST"])
def source_delete(request, source_id):
    source = get_object_or_404(DatabaseSource.objects.defer("password"), pk=source_id)
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        try:
            delete_source(source_id)
        except InspectionError as error:
            messages.error(request, str(error))
            return redirect("DB_EXTRACTION:source_detail", source_id=source_id)
        messages.success(request, "Connection and all its saved metadata were deleted.")
        return redirect("DB_EXTRACTION:source_list")
    return _render(request, "source_delete", {"page_title": "Delete database connection", "source": source, "run_count": source.extraction_runs.count()})


@require_safe
def run_list(request, source_id):
    source = get_object_or_404(DatabaseSource.objects.defer("password"), pk=source_id)
    return _render(request, "run_list", {"page_title": "Extraction history", "source": source, **pages.paginate(request, source.extraction_runs.all())})


@require_safe
def run_detail(request, source_id, run_id):
    source = get_object_or_404(DatabaseSource.objects.defer("password"), pk=source_id)
    run = get_object_or_404(ExtractionRun, pk=run_id, source=source)
    query = request.GET.get("q", "").strip()
    schema = request.GET.get("schema", "")
    return _render(request, "run_detail", {
        "page_title": f"Snapshot #{run.pk}", "source": source, "snapshot": run,
        "counts": pages.snapshot_counts(run), "schemas": run.schemas.all(),
        "query": query, "schema_filter": schema,
        **pages.paginate(request, pages.snapshot_tables(run, query, schema)),
    })


@require_safe
def table_detail(request, source_id, run_id, table_id):
    source = get_object_or_404(DatabaseSource.objects.defer("password"), pk=source_id)
    run = get_object_or_404(ExtractionRun, pk=run_id, source=source)
    table = get_object_or_404(DatabaseTable.objects.select_related("schema"), pk=table_id, schema__run=run)
    constraints = table.constraints.prefetch_related("columns__column")
    return _render(request, "table_detail", {
        "page_title": f"{table.schema.name}.{table.name}", "source": source,
        "snapshot": run, "table": table, "columns": table.columns.all(),
        "constraints": constraints, "indexes": table.indexes.all(),
    })
