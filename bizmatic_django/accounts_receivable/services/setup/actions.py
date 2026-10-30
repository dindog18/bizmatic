"""HTTP-facing setup actions; tests and confirmation receipts bind the exact configuration."""
import hashlib
import json
from copy import deepcopy

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.shortcuts import get_object_or_404

from db_extraction.models import DatabaseSource
from db_extraction.services.extraction import refresh_source
from db_extraction.services.postgres import InspectionError
from .. import configuration, configuration_chat, pages
from ..catalog import model
from . import context, database, documents


def prepare(mode, data, record_id=None, submit=False):
    values = data.get('configuration')
    if not isinstance(values, dict) or not values.get('setup_data'):
        raise ValidationError('Provide the current Record First configuration.')
    if record_id:
        saved = get_object_or_404(model(mode, 'ExtractionConfiguration'), pk=record_id)
        if values.get('source_type') != saved.source_type:
            raise ValidationError('Create a separate configuration to change its extraction source.')
    return configuration.prepare(mode, values, record_id, submit=submit, incomplete=not submit)


def identity(mode, record, user):
    values = configuration.snapshot(record)
    source = record.database_source if record.source_type == 'database' and record.database_source_id else None
    return {'module': mode, 'id': record.pk, 'revision': record.revision,
            'user': user.pk if user.is_authenticated else None,
            'source_revision': source.updated_at.isoformat() if source else None,
            'digest': hashlib.sha256(json.dumps(values, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def check_test(mode, record, user, token):
    try:
        receipt = signing.loads(token or '', salt='record-setup-test', max_age=1800)
    except signing.BadSignature:
        raise ValidationError('Run a mapping test before submitting. Test results expire after 30 minutes.') from None
    tested_identity = receipt.get('identity') if record.source_type == 'document' and 'identity' in receipt else receipt
    if tested_identity != identity(mode, record, user):
        raise ValidationError('The configuration or source changed after testing. Run the mapping test again.')
    return receipt.get('issues', []) if record.source_type == 'document' else []


def bootstrap(mode, data, record_id=None):
    record = get_object_or_404(model(mode, 'ExtractionConfiguration'), pk=record_id) if record_id else None
    if data.get('inspect_source'):
        source = get_object_or_404(DatabaseSource, pk=data['inspect_source'], enabled=True)
        try:
            run = refresh_source(source.pk)
        except InspectionError as error:
            raise ValidationError(str(error)) from error
        if run.status != 'completed':
            raise ValidationError(run.error_message)
    from accounts_receivable.ui import configuration_catalog
    return {'catalog': configuration_catalog(mode), 'sources': context.sources(None if data.get('inspect_source') else record), 'documents': context.documents(),
            'record': pages.configuration(record, mode) if record else None}



def perform(request, mode, action, data, record_id=None):
    if action == 'setup-preview':
        # Validate only the selected prefix: a later broken step or unfinished
        # destination mapping must not prevent inspecting an earlier result.
        values = deepcopy(data)
        config = values.get('configuration', {})
        setup = config.get('setup_data', {}) if isinstance(config, dict) else {}
        query = setup.get('database', {}) if isinstance(setup, dict) else {}
        recipe = query.get('pipeline', {}) if isinstance(query, dict) else {}
        steps = recipe.get('steps', []) if isinstance(recipe, dict) else []
        if not isinstance(steps, list):
            raise ValidationError('Provide an ordered list of transformation steps.')
        count = data.get('step', len(steps))
        if type(count) is not int or not 0 <= count <= len(steps):
            raise ValidationError('Choose a valid applied step to preview.')
        if not isinstance(recipe, dict) or config.get('source_type') != 'database':
            raise ValidationError('Choose the database query builder.')
        recipe['steps'] = steps[:count]
        query['mappings'] = []
        record = prepare(mode, values, record_id)
        from .pipeline import preview
        return preview(mode, record, limit=data.get('limit', 50), offset=data.get('offset', 0))
    if action == 'setup-context':
        return bootstrap(mode, data, record_id)
    if action == 'setup-document':
        return context.document_text(data.get('document_id'))
    if action in {'setup-chat-history', 'setup-chat-clear', 'setup-chat'}:
        from . import chat
        if action == 'setup-chat-history':
            return chat.load(request, mode, data)
        if action == 'setup-chat-clear':
            return chat.clear(request, mode, data)
        return chat.reply(request, mode, data, prepare(mode, data, record_id))
    if action in {'setup-update-review', 'setup-update-apply'}:
        from .. import database_updates
        record = get_object_or_404(model(mode, 'ExtractionConfiguration'), pk=record_id, source_type='database', status='submitted')
        if data.get('revision') != record.revision:
            raise ValidationError('The saved setup changed. Reload before updating data.', code='conflict')
        if action == 'setup-update-review':
            return database_updates.review(mode, record, request.user, 'update')
        if data.get('confirmed') is not True:
            raise ValidationError('Review and confirm the data update first.')
        saved, result = database_updates.apply(mode, record, request.user, 'update', data.get('migration_token'))
        return {'record':pages.configuration(saved, mode), 'result':result}
    record = prepare(mode, data, record_id, submit=action == 'setup-migration-apply' or action in {'setup-review', 'setup-save'} and data.get('submit') is True)
    if action in {'setup-migration-review', 'setup-migration-apply'}:
        from .. import database_updates
        if record.source_type != 'database':
            raise ValidationError('Choose a database source before migrating records.')
        if not record.name.strip():
            raise ValidationError('Give this configuration a name before reviewing the migration.')
        if action == 'setup-migration-review':
            try:
                tested = signing.loads(data.get('migration_test_token') or '', salt='database-migration-test', max_age=1800)
            except signing.BadSignature:
                raise ValidationError('Run Test query with the current mappings before reviewing the full migration.') from None
            if tested != identity(mode, record, request.user):
                raise ValidationError('The setup changed. Run Test query again before migration.')
            return database_updates.review(mode, record, request.user, 'migrate')
        if data.get('confirmed') is not True:
            raise ValidationError('Review and confirm the full migration first.')
        messages = configuration_chat.conversation(data.get('messages', []))
        saved, result = database_updates.apply(mode, record, request.user, 'migrate', data.get('migration_token'), messages)
        return {'record':pages.configuration(saved, mode), 'result':result}
    if action == 'setup-generate':
        if record.source_type != 'document':
            raise ValidationError('Choose document extraction to generate a prompt.')
        return documents.generate(mode, record, feedback=data.get('feedback'))
    if action == 'setup-test':
        if record.source_type == 'document':
            if not record.extraction_context.strip():
                raise ValidationError('Generate or enter an extraction prompt before testing.')
            result = documents.test(mode, record, data.get('text', ''), data.get('expected', {}), reuse_log=data.get('reuse_log'))
        else:
            result = database.test(mode, record, data.get('limit', 5))
            result['migration_test_token'] = signing.dumps(identity(mode, record, request.user), salt='database-migration-test')
        # A completed document test can be reviewed even when it reports issues.
        # Bind those issues to the exact configuration for explicit confirmation.
        receipt = {'identity': identity(mode, record, request.user), 'issues': result['issues']} if record.source_type == 'document' else identity(mode, record, request.user)
        result['test_token'] = signing.dumps(receipt, salt='record-setup-test') if record.source_type == 'document' or result['passed'] else None
        return json.loads(json.dumps(result, cls=DjangoJSONEncoder))
    if action == 'setup-review':
        if record.source_type == 'database':
            raise ValidationError('Review the full migration after Test query before saving a database setup.')
        if not record.name.strip():
            raise ValidationError('Give this configuration a name before saving.')
        submit = data.get('submit') is True
        issues = check_test(mode, record, request.user, data.get('test_token')) if submit else []
        receipt = {'identity': identity(mode, record, request.user), 'submit': submit}
        return {'confirmation_token': signing.dumps(receipt, salt='record-setup-review'), 'record': pages.configuration(record, mode), 'test_issues': issues}
    if action == 'setup-save':
        if record.source_type == 'database':
            raise ValidationError('Use Migrate all & save after the full migration review. A sample test alone cannot save a database setup.')
        submit = data.get('submit') is True
        try:
            receipt = signing.loads(data.get('confirmation_token', ''), salt='record-setup-review', max_age=1800)
        except signing.BadSignature:
            raise ValidationError('Review and confirm this configuration before saving.') from None
        if data.get('confirmed') is not True or receipt != {'identity': identity(mode, record, request.user), 'submit': submit}:
            raise ValidationError('The configuration changed or was not confirmed. Review it again before saving.')
        if submit:
            check_test(mode, record, request.user, data.get('test_token'))
        with transaction.atomic():
            saved = configuration.save(mode, configuration.snapshot(record), record_id, submit=submit, user=request.user)
            saved.assistant_messages = configuration_chat.conversation(data.get('messages', []))
            saved.save(update_fields=['assistant_messages'])
        return {'record': pages.configuration(saved, mode)}
    raise ValidationError('Unsupported setup action.')
