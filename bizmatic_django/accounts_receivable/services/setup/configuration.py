"""Validate record-first state and bridge it to the existing extraction/import profiles."""
import json
from django.core.exceptions import ValidationError
from ..catalog import fields, model


def validate_setup(record, mode, submit=False):
    setup = record.setup_data
    if not isinstance(setup, dict) or setup.get('version') != 1:
        raise ValidationError('Unsupported setup version. Reload the extraction setup.')
    if record.source_type == 'document':
        from .documents import validate_annotations
        document = setup.get('document')
        if not isinstance(document, dict):
            raise ValidationError('Provide the current document setup.')
        validate_annotations(mode, record.target_entity, document, complete=submit)
        record.sample_text = document.get('text', '')
        record.extraction_context = document.get('prompt', '')
        record.document_type = record.document_type or record.get_target_entity_display()
        record.field_instructions = {}
        record.line_field_instructions = {}
        for key, rule in document.get('rules', {}).items():
            group, name = key.split(':', 1)
            (record.line_field_instructions if group == 'line' else record.field_instructions)[name] = json.dumps(rule, ensure_ascii=False)
        if record.target_entity in {'purchase_order', 'delivery_receipt', 'sales_invoice'}:
            record.line_item_context = document.get('line_context') or 'Extract item rows when present; otherwise return lines: []. Every line field is optional. Exclude totals and summary rows.'
        if submit and not record.extraction_context.strip():
            raise ValidationError('Generate or enter the extraction prompt before submitting.')
        record.source_schema_snapshot = {}
    else:
        from .database import validate_query
        query = setup.get('database')
        if not isinstance(query, dict):
            raise ValidationError('Provide the current database query.')
        metadata = validate_query(mode, record, query, complete=submit)
        if metadata:
            record.source_table = metadata['tables']['base']
            record.source_key_fields = metadata.get('key_names', [reference.removeprefix('base.') for reference in query.get('keys', [])])
            record.field_mappings = {}
            record.line_item_mappings = {}
            for mapping in query.get('mappings', []):
                if not mapping.get('include') or mapping.get('method') == 'empty':
                    continue
                group, name = mapping['id'].split(':', 1)
                (record.line_item_mappings if group == 'line' else record.field_mappings)[name] = {'source': mapping['id'], 'transform': 'identity'}
            record.source_schema_snapshot = {'connection': record.database_source.name,
                'header_table': str(record.source_table), 'header_columns': [column.name for column in record.source_table.columns.all()],
                'tables': {alias: {'id': table.pk, 'name': str(table)} for alias, table in metadata['tables'].items()}}


def clean_output(mode, config, result):
    """Validate types, account lookups and required values without creating accounting records."""
    from ..extraction import normalize_lines, values_for, validate_totals
    issues = []
    if not isinstance(result, dict) or set(result) - {'record', 'lines', 'issues'} or not isinstance(result.get('record'), dict) or not isinstance(result.get('issues', []), list):
        raise ValidationError('Expected record, lines, and issues from extraction.')
    raw_lines = result.get('lines') if result.get('lines') is not None else []
    if not isinstance(raw_lines, list):
        raise ValidationError('Line items must be an array; use [] when there are none.')
    issues.extend(str(issue) for issue in result.get('issues', []))
    has_lines = config.target_entity in {'purchase_order', 'delivery_receipt', 'sales_invoice'}
    if not has_lines and raw_lines:
        issues.append('This record type does not have line items.')
    if len(raw_lines) > 1000:
        raise ValidationError('A record exceeds 1,000 line items.')
    if any(not isinstance(row, dict) for row in raw_lines):
        raise ValidationError('Each line item must be an object containing its field values.')
    converted_rows = []
    normalized = normalize_lines(mode, config, raw_lines) if has_lines else []
    line_rows = [(row, True) for row in normalized]
    for values, is_line in [(result['record'], False), *line_rows]:
        try:
            converted = values_for(mode, config, values, lines=is_line, canonical=config.source_type == 'document')
            converted_rows.append(converted)
            for field in fields(mode, config.target_entity, is_line):
                if field.name in converted and not field.is_relation:
                    field.clean(converted[field.name], None)
        except (ValidationError, ValueError, TypeError) as error:
            issues.extend(error.messages if isinstance(error, ValidationError) else [str(error)])
    if not issues and converted_rows:
        try:
            header = model(mode, config.target_entity)(**converted_rows[0])
            header.clean()
            line_records = []
            if has_lines:
                Line = model(mode, type(header).__name__+'Line')
                parent = {'purchase_order': 'purchase_order', 'delivery_receipt': 'delivery_receipt', 'sales_invoice': 'invoice'}[config.target_entity]
                for values in converted_rows[1:]:
                    line = Line(**values, **{parent: header})
                    line.clean()
                    line_records.append(line)
                numbers = [line.line_no for line in line_records]
                if len(set(numbers)) != len(numbers):
                    raise ValidationError('Line numbers must be unique within a record.')
            validate_totals(config.target_entity, header, line_records, header_values=result['record'], line_values=normalized)
        except (ValidationError, ValueError, TypeError) as error:
            issues.extend(error.messages if isinstance(error, ValidationError) else [str(error)])
    return list(dict.fromkeys(issues))
