"""Store drafts and explicitly submitted extraction instructions."""

import json
import re

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .catalog import fields, model, party_key, required_fields

EDITABLE = ["name", "description", "target_entity", "source_type", "database_source", "source_table", "line_source_table",
            "source_key_fields", "field_mappings", "line_item_mappings", "line_join_fields", "relation_lookups",
            "document_type", "extraction_context", "field_instructions", "line_field_instructions", "line_item_context",
            "sample_text", "encoding_rules", "setup_data"]
TRANSFORMS = {"trim", "identity", "uppercase", "date", "datetime", "decimal", "integer", "boolean", "json", "lookup"}


def snapshot(record):
    values = {name: getattr(record, name+"_id" if name in {"database_source", "source_table", "line_source_table"} else name)
              for name in EDITABLE}
    key = "customer" if record._meta.app_label == "accounts_receivable" else "supplier"
    values.update({key: getattr(record, key+"_id"), "source_schema_snapshot": record.source_schema_snapshot,
                   "revision": record.revision})
    return json.loads(json.dumps(values, cls=DjangoJSONEncoder))


def validate(record, mode, submit=False):
    target = record.target_entity
    header = {f.name for f in fields(mode, target)}
    line_fields = {f.name for f in fields(mode, target, True)} if target in {"purchase_order", "delivery_receipt", "sales_invoice"} else set()
    for name, allowed in [("field_mappings", header), ("field_instructions", header), ("line_item_mappings", line_fields), ("line_field_instructions", line_fields)]:
        value = getattr(record, name)
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValidationError(f"{name}: choose only fields from the selected record type.")
        if name.endswith("instructions") and any(not isinstance(text, str) for text in value.values()):
            raise ValidationError("Field instructions must be text.")
    rules = record.encoding_rules
    if not isinstance(rules, dict) or not isinstance(record.relation_lookups, dict):
        raise ValidationError("Encoding rules and account lookups must be objects.")
    for name, allowed in [("required_fields", header), ("line_required_fields", line_fields)]:
        values = rules.get(name, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or set(values) - allowed:
            raise ValidationError(f"Invalid {name}.")
    if rules.get("duplicate_policy", "review") not in {"review", "skip"}:
        raise ValidationError("MVP duplicate handling supports review or skip; existing records are never overwritten.")
    if rules.get("missing_value_policy", "review") != "review":
        raise ValidationError("Missing required values must be reviewed.")
    if rules.get("default_currency") and not re.fullmatch(r"[A-Z]{3}", rules["default_currency"]):
        raise ValidationError("Use a three-letter uppercase currency.")
    if rules.get("date_format", "YYYY-MM-DD") not in {"YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"}:
        raise ValidationError("Choose YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY.")
    if rules.get("decimal_separator", ".") not in {".", ","} or rules.get("thousands_separator", ",") not in {"", ".", ",", " "} or rules.get("decimal_separator", ".") == rules.get("thousands_separator", ","):
        raise ValidationError("Choose different decimal and thousands separators.")
    key = party_key(mode)
    for relation, lookup in record.relation_lookups.items():
        if relation != key or not isinstance(lookup, dict) or lookup.get("match_field") not in {key+"_code", "tax_identification_no", key+"_name"} or lookup.get("on_missing", "review") != "review":
            raise ValidationError("Resolve accounts by code, name, or tax ID; missing accounts require review.")
    if record.setup_data:
        from .setup.configuration import validate_setup
        validate_setup(record, mode, submit)
        return
    if record.source_type == "document":
        if submit and (not record.document_type.strip() or not record.extraction_context.strip() or (line_fields and not record.line_item_context.strip())):
            raise ValidationError("Provide the document type, extraction instructions, and line instructions where applicable.")
        record.source_schema_snapshot = {}
        return
    if record.database_source_id and not record.database_source.enabled:
        raise ValidationError("Choose an enabled database connection.")
    if not record.source_table_id and (record.field_mappings or record.line_item_mappings or record.line_source_table_id):
        raise ValidationError("Choose a header table before configuring database mappings.")
    if record.source_table_id:
        table = record.source_table
        if table.schema.run.status != "completed" or table.schema.run.source_id != record.database_source_id:
            raise ValidationError("Choose a table from a completed snapshot of the selected connection.")
        if record.line_source_table_id and record.line_source_table.schema.run_id != table.schema.run_id:
            raise ValidationError("Header and line tables must come from the same snapshot.")
        columns = set(table.columns.values_list("name", flat=True))
        line_columns = set(record.line_source_table.columns.values_list("name", flat=True)) if record.line_source_table_id else set()
        record.source_schema_snapshot = {"connection": record.database_source.name, "header_table": f"{table.schema.name}.{table.name}",
                                         "header_columns": sorted(columns), "line_columns": sorted(line_columns),
                                         "line_table": f"{record.line_source_table.schema.name}.{record.line_source_table.name}" if record.line_source_table_id else ""}
        keys = record.source_key_fields
        if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys) or set(keys) - columns or (submit and not keys):
            raise ValidationError("Select existing header key columns.")
        for name, available, allowed, required_name in [("field_mappings", columns, header, "required_fields"), ("line_item_mappings", line_columns, line_fields, "line_required_fields")]:
            mappings = getattr(record, name)
            for field, mapping in mappings.items():
                if not isinstance(mapping, dict):
                    raise ValidationError(f'{name}.{field} must be an object such as {{"source": "column_name", "transform": "identity"}}.')
                if not isinstance(mapping.get("transform", "identity"), str) or mapping.get("transform", "identity") not in TRANSFORMS:
                    raise ValidationError(f'{name}.{field}.transform must be one of: {", ".join(sorted(TRANSFORMS))}.')
                if mapping.get("source") and (not isinstance(mapping["source"], str) or mapping["source"] not in available):
                    raise ValidationError(f'{name}.{field}.source must be a column in the selected table: {", ".join(sorted(available))}.')
            if submit and (name == "field_mappings" or record.line_source_table_id):
                required = set(rules.get(required_name, [])) | required_fields(mode, target, name == "line_item_mappings")
                for field in required:
                    mapping = mappings.get(field, {})
                    if not mapping.get("source") and mapping.get("default", "") in {"", None} and not (field == "currency" and rules.get("default_currency")):
                        raise ValidationError(f"Map required field {field} or provide a default.")
        if not isinstance(record.line_join_fields, list):
            raise ValidationError("Line joins must be a list.")
        for pair in record.line_join_fields:
            if not isinstance(pair, dict) or pair.get("header_column") not in columns or pair.get("line_column") not in line_columns:
                raise ValidationError("Line joins must use columns from the selected tables.")
        if submit and record.line_source_table_id and not record.line_join_fields:
            raise ValidationError("Provide header-to-line joins.")
        if submit and line_fields and not record.line_source_table_id:
            raise ValidationError("Select a line table for this record type.")
    elif submit:
        raise ValidationError("Select a database connection and header table.")


def prepare(mode, data, record_id=None, submit=False, incomplete=False):
    record = get_object_or_404(model(mode, "ExtractionConfiguration").objects, pk=record_id) if record_id else model(mode, "ExtractionConfiguration")()
    if record_id:
        if data.get("revision") != record.revision:
            raise ValidationError("This configuration changed. Reload before saving.", code="conflict")
        if data.get("target_entity") != record.target_entity:
            raise ValidationError("Create a new configuration to change its record type.")
    data = dict(data)
    unnamed = incomplete and not data.get("name")
    if unnamed:
        data["name"] = "Untitled configuration"
    Form = modelform_factory(type(record), fields=[*EDITABLE, party_key(mode)])
    form = Form(data, instance=record)
    if not form.is_valid():
        raise ValidationError([f"{name}: {message}" for name, messages in form.errors.items() for message in messages])
    record = form.save(commit=False)
    # Django's optional JSON form fields normalize empty objects/lists to None.
    for name in ("field_mappings", "line_item_mappings", "relation_lookups", "field_instructions", "line_field_instructions", "encoding_rules", "setup_data"):
        if getattr(record, name) is None:
            setattr(record, name, {})
    for name in ("source_key_fields", "line_join_fields"):
        if getattr(record, name) is None:
            setattr(record, name, [])
    validate(record, mode, submit)
    if unnamed:
        record.name = ""
    return record


@transaction.atomic
def save(mode, data, record_id=None, submit=False, user=None):
    if record_id:
        get_object_or_404(model(mode, "ExtractionConfiguration").objects.select_for_update(), pk=record_id)
    record = prepare(mode, data, record_id, submit)
    record.revision = record.revision + 1 if record_id else 1
    record.status = "submitted" if submit else "draft"
    record.assistant_proposal = {}
    if submit:
        record.submitted_at = timezone.now()
        record.submitted_by = user if user and user.is_authenticated else None
        record.submitted_snapshot = {"configuration": snapshot(record)}
    record.save()
    return record
