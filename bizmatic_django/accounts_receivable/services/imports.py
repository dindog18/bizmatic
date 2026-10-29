"""Explicit, bounded PostgreSQL row imports using reviewed mappings only."""

import json
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from db_extraction.models import DatabaseSource
from db_extraction.services.postgres import connection_parameters
from .catalog import model, party_key, error_text
from .configuration import snapshot, validate
from .extraction import save_result


def mapped(row, mappings):
    result = {}
    for name, mapping in mappings.items():
        value = row.get(mapping.get("source")) if mapping.get("source") else None
        if value is None or value == "":
            value = mapping.get("default", "")
        if value is None or value == "":
            continue
        transform = mapping.get("transform", "identity")
        if transform == "trim":
            value = str(value).strip()
        elif transform == "uppercase":
            value = str(value).strip().upper()
        elif transform == "json" and isinstance(value, str):
            value = json.loads(value)
        result[name] = value
    return result


def read_rows(config, limit, offset):
    """Identifiers come from saved metadata; values are always bound parameters."""
    if config.setup_data.get("database"):
        from .setup.database import import_rows
        return import_rows("ar" if config._meta.app_label == "accounts_receivable" else "ap", config, limit, offset)
    source = config.database_source
    if not source.enabled:
        raise ValidationError("Enable the database connection before importing.")
    table = config.source_table
    columns = set(config.source_key_fields) | {value["source"] for value in config.field_mappings.values() if value.get("source")} | {pair["header_column"] for pair in config.line_join_fields}
    header_sql = sql.SQL("SELECT {columns} FROM {table} ORDER BY {keys} LIMIT %s OFFSET %s").format(
        columns=sql.SQL(", ").join(map(sql.Identifier, sorted(columns))), table=sql.Identifier(table.schema.name, table.name),
        keys=sql.SQL(", ").join(map(sql.Identifier, config.source_key_fields)))
    try:
        with psycopg.connect(**connection_parameters(source), row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            rows = connection.execute(header_sql, (limit, offset)).fetchall()
            result = []
            for row in rows:
                lines = []
                if config.line_source_table_id:
                    line_table = config.line_source_table
                    line_columns = {value["source"] for value in config.line_item_mappings.values() if value.get("source")}
                    if not line_columns:
                        raise ValidationError("Map at least one source line column.")
                    query = sql.SQL("SELECT {columns} FROM {table} WHERE {joins} LIMIT 1001").format(
                        columns=sql.SQL(", ").join(map(sql.Identifier, sorted(line_columns))),
                        table=sql.Identifier(line_table.schema.name, line_table.name),
                        joins=sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(pair["line_column"])) for pair in config.line_join_fields))
                    lines = connection.execute(query, [row[pair["header_column"]] for pair in config.line_join_fields]).fetchall()
                    if len(lines) > 1000:
                        raise ValidationError("A record exceeds the 1,000-line import limit.")
                result.append((row, lines))
            return result
    except psycopg.Error:
        raise ValidationError("The source query failed. Refresh its schema and check connection permissions.") from None


def execute(mode, record_id, data):
    request_id = UUID(str(data.get("request_id")))
    limit, offset = data.get("limit", 50), data.get("offset", 0)
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValidationError("Choose 1–100 records and a nonnegative offset.")
    with transaction.atomic():
        config = get_object_or_404(model(mode, "ExtractionConfiguration").objects.select_for_update(), pk=record_id)
        previous = model(mode, "DatabaseImportRun").objects.filter(request_id=request_id).first()
        if previous:
            if previous.configuration_id != config.pk:
                raise ValidationError("This request ID belongs to another configuration.")
            return previous
        if config.status != "submitted" or config.source_type != "database" or config.revision != data.get("revision"):
            raise ValidationError("Use the current submitted database configuration.")
        validate(config, mode, submit=True)
        run = model(mode, "DatabaseImportRun").objects.create(configuration=config, request_id=request_id, configuration_snapshot=snapshot(config))
    result = {"created": [], "skipped": [], "errors": [], "offset": offset, "limit": limit}
    try:
        rows = read_rows(config, limit, offset)
        for header, lines in rows:
            key = {name: header[name] for name in config.source_key_fields}
            key = json.loads(json.dumps(key, cls=DjangoJSONEncoder))
            try:
                with transaction.atomic():
                    current_source = DatabaseSource.objects.select_for_update().get(pk=config.database_source_id)
                    if not current_source.enabled or current_source.updated_at != config.database_source.updated_at:
                        raise ValidationError("The source connection changed during import. Review it before retrying.")
                    if not key or any(value is None for value in key.values()):
                        raise ValidationError("Source key values cannot be null.")
                    Target = model(mode, config.target_entity)
                    values = mapped(header, config.field_mappings)
                    if config.target_entity in {"customer", "supplier"}:
                        duplicate = Target.objects.filter(**{party_key(mode)+"_code": values.get(party_key(mode)+"_code")}).exists()
                    else:
                        duplicate = Target.objects.filter(source_database_id=config.database_source_id, source_table__schema__name=config.source_table.schema.name, source_table__name=config.source_table.name, source_record_key=key).exists()
                    if duplicate:
                        if config.encoding_rules.get("duplicate_policy", "review") == "skip":
                            result["skipped"].append(key)
                            continue
                        raise ValidationError("This source record was already imported. Review the existing record.")
                    record = save_result(mode, config, {"record": values, "lines": [mapped(row, config.line_item_mappings) for row in lines]}, database_source=config.database_source, source_table=config.source_table, source_key=key)
                    result["created"].append({"key": key, "id": record.pk})
            except (ValidationError, ValueError) as error:
                result["errors"].append({"key": key, "message": error_text(error)})
    except Exception as error:
        result["errors"].append({"message": error_text(error) if isinstance(error, (ValidationError, ValueError)) else "The import could not finish. Review the source connection and saved records before retrying."})
    run.status = "failed" if result["errors"] else "completed"
    run.result = result
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "result", "finished_at"])
    return run
