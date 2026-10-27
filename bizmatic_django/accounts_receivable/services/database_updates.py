"""Full source review followed by one atomic migration/update of local AP/AR data.

Review does not write anything. The signed receipt binds the entire source result,
destination records and configuration. Apply streams and validates again inside a
local transaction; an error or changed result rolls back every accounting write.
"""
import hashlib
import json
from copy import copy
from uuid import UUID, uuid4

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from db_extraction.models import DatabaseSource
from . import configuration
from .catalog import model, party_key, error_text, revision
from .extraction import normalize_lines, values_for, validate_totals
from .setup.database import stream_records

MAX_ERRORS = 200


def encoded(value):
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':'))


def identity(mode, config, user):
    return {'mode': mode, 'configuration': config.pk, 'user': getattr(user, 'pk', None),
            'digest': hashlib.sha256(encoded(configuration.snapshot(config)).encode()).hexdigest(),
            'source_revision': config.database_source.updated_at.isoformat()}


def local_record(mode, config, key, parsed, locked=False):
    Target = model(mode, config.target_entity)
    rows = Target.objects.select_for_update() if locked else Target.objects.all()
    if config.target_entity in {'supplier', 'customer'}:
        code = parsed['record'].get(party_key(mode)+'_code')
        converted = values_for(mode, config, parsed['record'], canonical=False)
        code = converted.get(party_key(mode)+'_code', code)
        rows = rows.filter(**{party_key(mode)+'_code': code})
    else:
        rows = rows.filter(source_database=config.database_source, source_table__schema__name=config.source_table.schema.name,
                           source_table__name=config.source_table.name, source_record_key=key)
    if rows.count() > 1:
        raise ValidationError('Several local records match this source identity. Resolve them before updating.')
    return rows.first()


def protected(record):
    for name in ('reconciliation_cases', 'payment_allocations', 'invoice_allocations', 'allocations'):
        related = getattr(record, name, None)
        if related is not None and related.exists():
            return True
    return False


def candidate(mode, config, key, parsed, locked=False):
    if parsed.get('issues'):
        raise ValidationError(parsed['issues'])
    if not key or any(value is None for value in key.values()):
        raise ValidationError('Source identifiers cannot be empty.')
    existing = local_record(mode, config, key, parsed, locked)
    Target = model(mode, config.target_entity)
    header = copy(existing) if existing else Target()
    values = values_for(mode, config, parsed['record'], canonical=False)
    for name, value in values.items():
        setattr(header, name, value)
    if config.target_entity not in {'supplier', 'customer'}:
        header.source_database = config.database_source
        header.source_table = config.source_table
        header.source_record_key = key
        header.imported_at = existing.imported_at if existing else timezone.now()
    header.full_clean()
    has_lines = config.target_entity in {'purchase_order', 'delivery_receipt', 'sales_invoice'}
    raw_lines = parsed.get('lines') if parsed.get('lines') is not None else []
    if not isinstance(raw_lines, list) or len(raw_lines) > 1000 or (not has_lines and raw_lines):
        raise ValidationError('Provide an array of optional line items (maximum 1,000 per record).')
    if has_lines:
        raw_lines = normalize_lines(mode, config, raw_lines)
    previous_lines = list(existing.lines.select_for_update().order_by('line_no')) if existing and has_lines and locked else list(existing.lines.order_by('line_no')) if existing and has_lines else []
    previous = {line.line_no: line for line in previous_lines}
    lines, numbers = [], set()
    if has_lines:
        Line = model(mode, Target.__name__+'Line')
        parent = {'purchase_order':'purchase_order', 'delivery_receipt':'delivery_receipt', 'sales_invoice':'invoice'}[config.target_entity]
        try:
            used = {int(row['line_no']) for row in raw_lines if row.get('line_no') not in (None, '')}
        except (ValueError, TypeError, OverflowError):
            raise ValidationError('Line no must be a whole number. Correct its mapping or use automatic numbering.') from None
        next_number = 1
        for raw in raw_lines:
            raw = dict(raw)
            if raw.get('line_no') in (None, ''):
                while next_number in used:
                    next_number += 1
                raw['line_no'] = next_number
                used.add(next_number)
            converted = values_for(mode, config, raw, lines=True, canonical=False)
            number = converted['line_no']
            if number in numbers:
                raise ValidationError('Line numbers must be unique within a source record.')
            numbers.add(number)
            line = copy(previous[number]) if number in previous else Line()
            for name, value in converted.items():
                setattr(line, name, value)
            setattr(line, parent, header)
            try:
                line.full_clean(exclude=[parent], validate_unique=False, validate_constraints=False)
            except ValidationError as error:
                detail = '; '.join(f'{name}: {"; ".join(messages)}' for name, messages in error.message_dict.items()) if hasattr(error, 'message_dict') else error_text(error)
                raise ValidationError(f'Line {number}: {detail}') from error
            lines.append(line)
        validate_totals(config.target_entity, header, lines, header_values=parsed['record'], line_values=raw_lines)
        if not raw_lines:
            lines = previous_lines  # An omitted item collection does not erase saved evidence.
            numbers = set(previous)
    changes = existing is None or any(getattr(existing, name) != getattr(header, name) for name in values)
    if has_lines:
        changes = changes or set(previous) != numbers
        changes = changes or any(line.line_no not in previous or any(field.value_from_object(line) != field.value_from_object(previous[line.line_no])
                              for field in line._meta.fields if not field.primary_key and not field.is_relation) for line in lines)
    if existing and changes and config.target_entity not in {'supplier', 'customer'}:
        if protected(existing) or any(getattr(line, 'matches', None) is not None and line.matches.exists() for line in previous_lines):
            raise ValidationError('This record is used in reconciliation or payment allocation. Resolve that workflow before changing its source data.')
        state = next((getattr(existing, name) for name in ('status', 'receipt_status', 'delivery_status', 'invoice_status', 'payment_status') if hasattr(existing, name)), '')
        if state in {'closed', 'cancelled', 'paid', 'reconciled', 'cleared', 'approved', 'posted', 'void', 'voided'}:
            raise ValidationError('This accounting record is finalized. Review its status before updating it.')
    # Bind resolved account IDs and converted values as well as source values.
    # Server-generated retrieval/save timestamps must not invalidate a review.
    def normalized(record):
        return {field.name:field.value_from_object(record) for field in record._meta.fields
                if field.name not in {'created_at', 'updated_at', 'imported_at'} and not field.primary_key}
    local_hash = {'existing':revision(existing, [revision(line) for line in previous_lines]) if existing else None,
                  'header':normalized(header), 'lines':[normalized(line) for line in lines]}
    return header, lines, previous_lines, 'created' if not existing else 'updated' if changes else 'unchanged', local_hash


def uniqueness(record):
    """Detect collisions between source rows before either row is persisted."""
    groups = [(field.name,) for field in record._meta.fields if field.unique and not field.primary_key]
    groups += [tuple(group) for group in record._meta.unique_together]
    groups += [tuple(constraint.fields) for constraint in record._meta.constraints if getattr(constraint, 'fields', ()) and getattr(constraint, 'condition', None) is None]
    for names in groups:
        values = [record._meta.get_field(name).value_from_object(record) for name in names]
        if all(value is not None for value in values):
            yield encoded([names, values])


def write_candidate(header, lines, previous, operation):
    if operation == 'unchanged':
        return
    header.save()
    if not lines or lines is previous:
        return
    parent = next(field.name for field in lines[0]._meta.fields if field.is_relation)
    numbers = {line.line_no for line in lines}
    for line in previous:
        if line.line_no not in numbers:
            line.delete()
    for line in lines:
        setattr(line, parent, header)
        line.save()


def scan(mode, config, apply=False):
    summary = {'count':0, 'created':0, 'updated':0, 'unchanged':0, 'error_count':0, 'errors':[]}
    fingerprint, seen = hashlib.sha256(), set()
    for key, parsed in stream_records(mode, config):
        key = json.loads(encoded(key))
        summary['count'] += 1
        try:
            header, lines, old_lines, operation, local_hash = candidate(mode, config, key, parsed, locked=apply)
            for unique in uniqueness(header):
                if unique in seen:
                    raise ValidationError('Different source identifiers produce the same unique accounting reference or account code. Refine the mapping or row conditions.')
                seen.add(unique)
            fingerprint.update(encoded([key, parsed, local_hash, operation]).encode()+b'\n')
            summary[operation] += 1
            if apply:
                write_candidate(header, lines, old_lines, operation)
        except (ValidationError, ValueError, TypeError, OverflowError, IntegrityError) as error:
            summary['error_count'] += 1
            message = 'An accounting uniqueness constraint conflicts with this source record.' if isinstance(error, IntegrityError) else '; '.join(f'{name}: {"; ".join(messages)}' for name, messages in error.message_dict.items()) if isinstance(error, ValidationError) and hasattr(error, 'message_dict') else error_text(error)
            if apply:
                raise ValidationError('Source '+encoded(key)+': '+message+'. All changes were rolled back.') from error
            if len(summary['errors']) < MAX_ERRORS:
                summary['errors'].append({'key':key, 'message':message})
    if not summary['count']:
        summary['error_count'] = 1
        summary['errors'].append({'key':{}, 'message':'No source records match this query. Adjust the row conditions.'})
    summary.update(passed=not summary['error_count'], fingerprint=fingerprint.hexdigest(), errors_truncated=summary['error_count']>len(summary['errors']))
    return summary


def review(mode, config, user, operation):
    configuration.validate(config, mode, submit=True)
    result = scan(mode, config)
    if result['passed']:
        receipt = {'identity':identity(mode, config, user), 'operation':operation,
                   'fingerprint':result['fingerprint'], 'count':result['count'], 'request_id':str(uuid4())}
        result['migration_token'] = signing.dumps(receipt, salt='database-full-migration')
    return result


def apply(mode, config, user, operation, token, messages=None):
    configuration.validate(config, mode, submit=True)
    try:
        receipt = signing.loads(token or '', salt='database-full-migration', max_age=1800)
    except signing.BadSignature:
        raise ValidationError('Review the full migration again. Reviews expire after 30 minutes.') from None
    if receipt.get('identity') != identity(mode, config, user) or receipt.get('operation') != operation:
        raise ValidationError('The setup or source connection changed. Run the full review again.', code='conflict')
    Run = model(mode, 'DatabaseImportRun')
    with transaction.atomic():
        source = DatabaseSource.objects.select_for_update().get(pk=config.database_source_id)
        if not source.enabled or source.updated_at != config.database_source.updated_at:
            raise ValidationError('The database connection changed. Review again.', code='conflict')
        previous = Run.objects.filter(request_id=UUID(receipt['request_id'])).first()
        if previous:
            if previous.configuration_id is None:
                raise ValidationError('This setup was deleted after its migration. Its accounting records remain. Review a new setup before continuing.', code='conflict')
            return previous.configuration, previous.result
        if config.pk:
            current = get_object_or_404(type(config).objects.select_for_update(), pk=config.pk)
            if current.revision != config.revision:
                raise ValidationError('The saved configuration changed. Reload and review again.', code='conflict')
        result = scan(mode, config, apply=True)
        if not result['passed'] or result['fingerprint'] != receipt['fingerprint'] or result['count'] != receipt['count']:
            raise ValidationError('The source or local accounting records changed after review. All changes were rolled back. Review the full result again.', code='conflict')
        if operation == 'migrate':
            saved = configuration.save(mode, configuration.snapshot(config), config.pk, submit=True, user=user)
            saved.assistant_messages = messages or []
            saved.save(update_fields=['assistant_messages'])
        else:
            saved = current
        result.pop('migration_token', None)
        Run.objects.create(configuration=saved, request_id=UUID(receipt['request_id']),
                           configuration_snapshot=configuration.snapshot(saved), status='completed', result={**result, 'operation':operation}, finished_at=timezone.now())
    return saved, {**result, 'operation':operation}
