"""Query helpers for connection lists and metadata browsing."""

from django.core.paginator import Paginator
from django.db.models import Count, Q

from ..models import DatabaseColumn, DatabaseConstraint, DatabaseIndex, DatabaseTable


def paginate(request, records, size=25):
    query = request.GET.copy()
    query.pop("page", None)
    return {"page_obj": Paginator(records, size).get_page(request.GET.get("page")), "page_query": query.urlencode()}


def snapshot_counts(run):
    if run is None:
        return dict(schemas=0, tables=0, columns=0, constraints=0, indexes=0)
    return {
        "schemas": run.schemas.count(),
        "tables": DatabaseTable.objects.filter(schema__run=run).count(),
        "columns": DatabaseColumn.objects.filter(table__schema__run=run).count(),
        "constraints": DatabaseConstraint.objects.filter(table__schema__run=run).count(),
        "indexes": DatabaseIndex.objects.filter(table__schema__run=run).count(),
    }


def snapshot_tables(run, query="", schema=""):
    tables = DatabaseTable.objects.filter(schema__run=run).select_related("schema").annotate(
        column_count=Count("columns", distinct=True), constraint_count=Count("constraints", distinct=True),
        index_count=Count("indexes", distinct=True),
    ).order_by("schema__name", "name")
    if query:
        tables = tables.filter(Q(name__icontains=query) | Q(comment__icontains=query))
    if schema:
        tables = tables.filter(schema__name=schema)
    return tables
