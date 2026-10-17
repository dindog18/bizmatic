"""Persist each catalog inspection as an independent, atomic metadata snapshot."""

import logging
from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from ..models import (
    ConstraintColumn, DatabaseColumn, DatabaseConstraint, DatabaseIndex,
    DatabaseSchema, DatabaseSource, DatabaseTable, ExtractionRun,
)
from .postgres import EXTRACTOR_VERSION, InspectionError, inspect_database

logger = logging.getLogger(__name__)
RELATION_KINDS = {"r": "table", "p": "partitioned", "f": "foreign", "v": "view", "m": "materialized_view"}
CONSTRAINT_TYPES = {"p": "primary_key", "f": "foreign_key", "u": "unique", "c": "check", "x": "exclusion", "n": "not_null"}
ACTIONS = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
MATCH_TYPES = {"f": "FULL", "p": "PARTIAL", "s": "SIMPLE"}


def _persist_snapshot(run, snapshot):
    """OID maps exist only for this run; names are the persisted object identity."""
    schemas = {}
    tables = {}
    columns = {}
    for row in snapshot.schemas:
        fields = {key: value for key, value in row.items() if key != "oid"}
        schemas[row["oid"]] = DatabaseSchema.objects.create(run=run, **fields)
    for row in snapshot.tables:
        fields = {key: value for key, value in row.items() if key not in {"oid", "schema_oid", "relation_kind"}}
        tables[row["oid"]] = DatabaseTable.objects.create(
            schema=schemas[row["schema_oid"]], relation_kind=RELATION_KINDS[row["relation_kind"]], **fields,
        )
    for row in snapshot.columns:
        fields = {key: value for key, value in row.items() if key != "table_oid"}
        columns[(row["table_oid"], row["ordinal_position"])] = DatabaseColumn.objects.create(
            table=tables[row["table_oid"]], **fields,
        )
    for row in snapshot.constraints:
        constraint = DatabaseConstraint.objects.create(
            table=tables[row["table_oid"]], name=row["name"], definition=row["definition"],
            constraint_type=CONSTRAINT_TYPES[row["constraint_type"]],
            referenced_schema=row["referenced_schema"], referenced_table=row["referenced_table"],
            update_action=ACTIONS.get(row["update_code"], "") if row["constraint_type"] == "f" else "",
            delete_action=ACTIONS.get(row["delete_code"], "") if row["constraint_type"] == "f" else "",
            match_type=MATCH_TYPES.get(row["match_code"], "") if row["constraint_type"] == "f" else "",
            is_deferrable=row["is_deferrable"], initially_deferred=row["initially_deferred"], is_validated=row["is_validated"],
        )
        targets = row["referenced_columns"] or []
        for position, column_position in enumerate(row["column_positions"] or [], start=1):
            # Exclusion constraints may use expressions instead of a column (column number zero).
            column = columns.get((row["table_oid"], column_position))
            if column is not None:
                ConstraintColumn.objects.create(
                    constraint=constraint, column=column, position=position,
                    referenced_column_name=targets[position - 1] if position <= len(targets) else "",
                )
    for row in snapshot.indexes:
        fields = {key: value for key, value in row.items() if key != "table_oid"}
        DatabaseIndex.objects.create(table=tables[row["table_oid"]], **fields)


def refresh_source(source_id: int) -> ExtractionRun:
    """Keep failed attempts and previous successful snapshots without partial metadata."""
    with transaction.atomic():
        source = DatabaseSource.objects.select_for_update().get(pk=source_id)
        if not source.enabled:
            raise InspectionError("Enable this connection before refreshing its schema.")
        # A terminated web process must not leave refresh permanently blocked.
        source.extraction_runs.filter(status="running", started_at__lt=timezone.now() - timedelta(minutes=10)).update(
            status="failed", finished_at=timezone.now(), error_message="The previous refresh was interrupted."
        )
        if source.extraction_runs.filter(status="running").exists():
            raise InspectionError("A schema refresh is already running for this connection.")
        run = ExtractionRun.objects.create(
            source=source, status="running", started_at=timezone.now(), database_name=source.database_name,
            included_schemas=list(source.included_schemas), extractor_version=EXTRACTOR_VERSION,
        )
    try:
        snapshot = inspect_database(source)
        with transaction.atomic():
            current = DatabaseSource.objects.select_for_update().get(pk=source_id)
            if current.updated_at != source.updated_at:
                raise InspectionError("Connection settings changed during extraction. Refresh again using the updated settings.")
            if not ExtractionRun.objects.filter(pk=run.pk, status="running").exists():
                raise InspectionError("This refresh was superseded. Start a new refresh.")
            _persist_snapshot(run, snapshot)
            run.database_name = snapshot.database_name
            run.server_version = snapshot.server_version
            run.status = "completed"
            run.finished_at = timezone.now()
            run.save(update_fields=["database_name", "server_version", "status", "finished_at"])
    except Exception as error:
        # Do not log exception text/tracebacks: database errors may contain secrets.
        if isinstance(error, InspectionError):
            message = str(error)
        elif isinstance(error, ImproperlyConfigured):
            message = "The credential key is unavailable or invalid. Ask an administrator to restore the configured key."
        else:
            message = "The snapshot could not be saved. Check the database configuration and retry."
        logger.warning("Database metadata run %s failed (%s)", run.pk, type(error).__name__)
        run.status = "failed"
        run.finished_at = timezone.now()
        run.error_message = message
        ExtractionRun.objects.filter(pk=run.pk).update(status=run.status, finished_at=run.finished_at, error_message=message)
    return run


def delete_source(source_id: int) -> None:
    """Delete local snapshots explicitly before the protected source; never touch the source DB."""
    with transaction.atomic():
        source = DatabaseSource.objects.select_for_update().defer("password").get(pk=source_id)
        if source.extraction_runs.filter(status="running", started_at__gte=timezone.now() - timedelta(minutes=10)).exists():
            raise InspectionError("Wait for the current schema refresh to finish before deleting this connection.")
        source.extraction_runs.all().delete()
        source.delete()
