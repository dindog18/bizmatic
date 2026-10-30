"""Legacy setup context, explicit resets, previews and reviewed saves for AP/AR."""
import hashlib
import json

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404

from db_extraction.models import DatabaseSource, DatabaseTable
from db_extraction.services.extraction import refresh_source
from db_extraction.services.postgres import InspectionError
from document_extraction.models import DocExtractionLog
from . import configuration, llm, pages
from .assistant import attempt_error
from .catalog import model, party_key, required_fields, TARGETS
from .extraction import SYSTEM as EXTRACTION_SYSTEM, definition

def selected_scope(mode, data, record=None):
    selection = data.get('selection')
    if not isinstance(selection, dict) or selection.get('target_entity') not in TARGETS[mode] or selection.get('source_type') not in {'database', 'document'}:
        raise ValidationError('Select a record type and document or database extraction before starting this chat.')
    if record and (selection['target_entity'] != record.target_entity or selection['source_type'] != record.source_type):
        raise ValidationError('This chat belongs to another selection. Switch to its record type and source before continuing.')
    return {key: selection[key] for key in ('target_entity', 'source_type')}


@transaction.atomic
def reset_context(mode, data, record_id=None):
    """Forget working answers as well as messages; retain prior submissions only as audit evidence."""
    selection = selected_scope(mode, data)
    if data.get('confirmed') is not True:
        raise ValidationError('Confirm the context reset before clearing this setup.')
    cls = model(mode, 'ExtractionConfiguration')
    record = get_object_or_404(cls.objects.select_for_update(), pk=record_id) if record_id else cls(**selection)
    if record_id:
        if data.get('revision') != record.revision:
            raise ValidationError('This configuration changed. Reload before resetting its context.', code='conflict')
        selected_scope(mode, data, record)
    record_first = isinstance(record.setup_data, dict) and record.setup_data.get('version') == 1
    clean = cls(**selection)
    for name in (*configuration.EDITABLE, party_key(mode)):
        field = cls._meta.get_field(name)
        setattr(record, field.attname, getattr(clean, field.attname))
    # A neutral saved label prevents an old business rule in the name leaking into the next prompt.
    record.name = f'{record.get_target_entity_display()} setup' if record_id else ''
    target = selection['target_entity']
    has_lines = target in {'purchase_order', 'delivery_receipt', 'sales_invoice'}
    record.encoding_rules = {
        'date_format': 'YYYY-MM-DD', 'decimal_separator': '.', 'thousands_separator': ',',
        'default_currency': 'PHP', 'duplicate_policy': 'review', 'missing_value_policy': 'review',
        'required_fields': sorted(required_fields(mode, target)),
        'line_required_fields': sorted(required_fields(mode, target, True)) if has_lines else [],
    }
    if record_first:
        record.setup_data = {'version': 1, 'document': {'text': '', 'prompt': '', 'rules': {}}} if selection['source_type'] == 'document' else {'version': 1, 'database': {'database': '', 'table': '', 'keys': [], 'joins': [], 'mappings': [], 'filters': {'logic': 'all', 'children': []}, 'sorts': [], 'distinct': False}}
    record.source_schema_snapshot = {}
    record.assistant_messages = []
    record.assistant_proposal = {}
    record.status = 'draft'
    if record_id:
        record.revision += 1
        record.save()
    return {'record': pages.configuration(record, mode), 'selection': selection}


def setup_context(mode, data, record_id=None):
    """Refresh selected requirements and metadata without changing a configuration or chat."""
    from accounts_receivable.ui import configuration_catalog
    selection = selected_scope(mode, data)
    record = draft(mode, data, record_id) if 'configuration' in data else None
    if record:
        selected_scope(mode, data, record)
    target = next(item for item in configuration_catalog(mode) if item['key'] == selection['target_entity'])
    database = selection['source_type'] == 'database'
    if data.get('inspect_schema'):
        if not database or not record or not record.database_source_id:
            raise ValidationError('Choose a database connection before refreshing its schema.')
        context_tool(mode, record, {'name': 'inspect_schema', 'source_id': record.database_source_id})
    available = sources() if database else {'sources': [], 'tables': []}
    parameters = ['name', 'account scope', 'formatting and review rules']
    parameters += ['database_source', 'source_table', 'source_key_fields', 'field_mappings'] if database else ['document_type', 'extraction_context']
    return {'selection': selection, 'catalog': [target], 'parameters': parameters,
            'features': ['Account lookup by code, name or tax ID', 'Missing values require review'] if any(field['type'] == 'lookup' for field in target['fields']) else ['Create master records from extracted fields', 'Missing values require review'],
            **available}


def sources():
    connections = list(DatabaseSource.objects.filter(enabled=True).values('id', 'name'))
    tables = []
    for source in connections:
        latest = DatabaseSource.objects.get(pk=source['id']).extraction_runs.filter(status='completed').order_by('-pk').first()
        if not latest:
            continue
        for table in DatabaseTable.objects.filter(schema__run=latest).select_related('schema').prefetch_related('columns', 'constraints')[:100]:
            tables.append({'id': table.pk, 'source_id': source['id'], 'snapshot': latest.pk,
                           'name': str(table), 'label': f'{table} · snapshot #{latest.pk}',
                           'columns': list(table.columns.values_list('name', flat=True)),
                           'column_definitions': list(table.columns.values('name', 'formatted_type', 'nullable')),
                           'constraints': list(table.constraints.values('constraint_type', 'definition'))})
    return {'sources': connections, 'tables': tables, 'table_limit_per_source': 100}


def conversation(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValidationError('Conversation must contain at most 100 messages.')
    result = []
    for item in value:
        if not isinstance(item, dict) or item.get('role') not in {'user', 'assistant'} or not isinstance(item.get('content'), str) or len(item['content']) > 16000:
            raise ValidationError('Invalid conversation message.')
        result.append({key: item[key] for key in ('role', 'content')})
    return result


def draft(mode, data, record_id):
    values = data.get('configuration')
    if not isinstance(values, dict):
        raise ValidationError('Provide the current configuration.')
    record = configuration.prepare(mode, values, record_id, incomplete=True)
    return record


def context_tool(mode, record, tool):
    if not isinstance(tool, dict):
        raise ValidationError('Invalid assistant context tool.')
    if record.source_type != 'database':
        raise ValidationError('Database context tools belong to a database setup chat.')
    if tool.get('name') == 'inspect_schema':
        source = DatabaseSource.objects.filter(pk=tool.get('source_id'), enabled=True).first()
        if source is None:
            raise ValidationError('Choose an available database connection before inspecting its schema.')
        try:
            run = refresh_source(source.pk)
        except InspectionError as error:
            raise ValidationError(str(error)) from error
        if run.status != 'completed':
            raise ValidationError(run.error_message)
        return sources()
    if tool.get('name') == 'sample_rows':
        from .imports import read_rows
        if record.source_type != 'database':
            raise ValidationError('Select a database source before reading sample rows.')
        if not record.source_table_id or not record.source_key_fields:
            raise ValidationError('Select a table and its record keys before reading sample rows.')
        configuration.validate(record, mode)
        rows = read_rows(record, 1, 0)
        return {'sample_rows': json.loads(json.dumps(rows, cls=DjangoJSONEncoder))}
    raise ValidationError('Unsupported assistant context tool.')


def preview(mode, data, record_id=None):
    record = draft(mode, data, record_id)
    if record.source_type != 'document':
        raise ValidationError('Choose document extraction to preview a document.')
    text = record.sample_text
    if data.get('text_log_id'):
        sample = DocExtractionLog.objects.filter(pk=data['text_log_id']).first()
        if sample is None:
            raise ValidationError('This extracted document is no longer available. Choose another sample.')
        text = sample.markdown_text
    if not text or not text.strip():
        raise ValidationError('Paste example text or select an extracted document first.')
    has_lines = record.target_entity in {'purchase_order', 'delivery_receipt', 'sales_invoice'}
    context = {'configuration': configuration.snapshot(record), 'document_text': text,
               'fields': definition(mode, record.target_entity),
               'line_fields': definition(mode, record.target_entity, True) if has_lines else []}
    log, result = llm.run(mode, record, 'configuration', EXTRACTION_SYSTEM, context)
    if result is None:
        raise attempt_error(log.error_message, log)
    try:
        if set(result) - {'record', 'lines', 'issues'} or not isinstance(result.get('record'), dict) or not isinstance(result.get('lines', []), list) or not isinstance(result.get('issues', []), list):
            raise ValidationError('Expected a preview containing record, lines, and issues.')
        allowed = {item['name'] for item in context['fields']}
        line_allowed = {item['name'] for item in context['line_fields']}
        if set(result['record']) - allowed or any(not isinstance(row, dict) or set(row) - line_allowed for row in result.get('lines', [])) or (result.get('lines') and not has_lines):
            raise ValidationError('The preview contains fields outside the destination schema.')
        from .extraction import values_for
        result.setdefault('lines', [])
        issues = result.setdefault('issues', [])
        for values, line in [(result['record'], False), *[(row, True) for row in result.get('lines', [])]]:
            try:
                values_for(mode, record, values, lines=line)
            except (ValidationError, ValueError, TypeError) as error:
                issues.extend(error.messages if isinstance(error, ValidationError) else ['A sample value needs review.'])
        log.status = 'completed'
        log.save(update_fields=['status', 'updated_at'])
        return {'preview': result, 'llm_log_no': log.pk, 'sample_text': text}
    except ValidationError as error:
        log.status = 'failed'
        log.error_message = '; '.join(error.messages)
        log.save(update_fields=['status', 'error_message', 'updated_at'])
        raise attempt_error(log.error_message, log) from error


def review_identity(mode, data, record_id, user):
    values = data.get('configuration', {})
    # Do not sign arbitrary client metadata or assistant-supplied status fields.
    body = {key: values.get(key) for key in [*configuration.EDITABLE, party_key(mode), 'revision']}
    return {'mode': mode, 'id': record_id, 'user': user.pk if user.is_authenticated else None,
            'submit': data.get('submit') is True,
            'digest': hashlib.sha256(json.dumps(body, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()}


def review(mode, data, record_id, user):
    configuration.prepare(mode, data.get('configuration', {}), record_id, submit=data.get('submit') is True)
    return {'confirmation_token': signing.dumps(review_identity(mode, data, record_id, user), salt='configuration-review')}


def confirm(mode, data, record_id, user):
    try:
        reviewed = signing.loads(data.get('confirmation_token', ''), salt='configuration-review', max_age=1800)
    except signing.BadSignature:
        raise ValidationError('Review this configuration again before saving.') from None
    if data.get('confirmed') is not True or reviewed != review_identity(mode, data, record_id, user):
        raise ValidationError('The configuration changed or was not confirmed. Review it again before saving.')
    values = dict(data.get('configuration', {}))
    history = conversation(data.get('messages', []))
    record = configuration.save(mode, values, record_id, submit=data.get('submit') is True, user=user)
    record.assistant_messages = history
    record.save(update_fields=['assistant_messages'])
    return record
