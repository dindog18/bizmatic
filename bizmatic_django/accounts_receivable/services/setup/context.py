"""Read destination definitions, saved schema relationships and extracted text choices."""
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from db_extraction.models import DatabaseSource, DatabaseTable
from document_extraction.models import DocExtractionLog, LLMExtractionLog, Document


def catalog(mode, target):
    from accounts_receivable.ui import configuration_catalog
    return next(item for item in configuration_catalog(mode) if item['key'] == target)


def field_catalog(mode, target):
    definition = catalog(mode, target)
    return [{**field, 'id': group+':'+field['key'], 'group': group}
            for group, values in [('header', definition['fields']), ('line', definition['lineFields'])]
            for field in values]


def sources(record=None):
    result = []
    for source in DatabaseSource.objects.filter(enabled=True):
        run = source.extraction_runs.filter(status='completed').order_by('-pk').first()
        if record and record.source_table_id and record.database_source_id == source.pk:
            run = record.source_table.schema.run
        tables = []
        if run:
            for table in DatabaseTable.objects.filter(schema__run=run).select_related('schema').prefetch_related('columns', 'constraints__columns__column'):
                columns = [{'name': col.name, 'type': 'boolean' if col.type_name == 'bool' else 'number' if any(word in col.formatted_type.lower() for word in ['int', 'numeric', 'decimal', 'double', 'real']) else 'date' if 'date' in col.formatted_type or 'timestamp' in col.formatted_type else 'text', 'formatted_type': col.formatted_type, 'nullable': col.nullable} for col in table.columns.all()]
                keys, references = [], []
                for constraint in table.constraints.all():
                    pairs = list(constraint.columns.all())
                    if constraint.constraint_type == 'primary_key':
                        keys = [pair.column.name for pair in pairs]
                    if constraint.constraint_type == 'foreign_key':
                        references.append({'name': constraint.name, 'table_name': constraint.referenced_schema+'.'+constraint.referenced_table,
                                           'pairs': [{'column': pair.column.name, 'target': pair.referenced_column_name} for pair in pairs]})
                for column in columns:
                    if column['name'] in keys:
                        column['key'] = 'Primary key'
                tables.append({'id': str(table.pk), 'name': str(table), 'columns': columns, 'keys': keys, 'references': references})
            by_name = {table['name']: table['id'] for table in tables}
            for table in tables:
                for reference in table['references']:
                    reference['table'] = by_name.get(reference['table_name'], '')
        result.append({'id': str(source.pk), 'name': source.name, 'revision': source.updated_at.isoformat(), 'snapshot': run.pk if run else None, 'tables': tables})
    return result


def documents():
    # Share routing's preference: accurate extraction first, then the latest usable result.
    from router.services.execution import select_text
    result = []
    for document in Document.objects.prefetch_related('text_logs', 'llm_logs').order_by('-pk')[:100]:
        try:
            row = select_text(document)
        except ValidationError:
            continue
        kind = 'llm' if isinstance(row, LLMExtractionLog) else 'text'
        result.append({'id': f'{kind}:{row.pk}', 'name': document.file_name, 'updated_at': row.updated_at.isoformat()})
    return result


def document_text(document_id):
    value = str(document_id)
    kind, pk = value.split(':', 1) if ':' in value else ('text', value)
    if kind not in {'text', 'llm'} or not pk.isdigit():
        raise ValidationError('Choose an available extracted document.')
    cls = LLMExtractionLog if kind == 'llm' else DocExtractionLog
    row = get_object_or_404(cls.objects.select_related('fk_document_no'), pk=int(pk))
    if not row.markdown_text or not row.markdown_text.strip() or row.error_message or isinstance(row, LLMExtractionLog) and row.status != 'completed':
        raise ValidationError('This document has no successful extracted text. Choose another document or paste text.')
    return {'text': row.markdown_text, 'id': f'{kind}:{row.pk}', 'name': row.fk_document_no.file_name}
