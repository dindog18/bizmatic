"""Small, ordered PostgreSQL transformation builder shared by AP and AR.

Steps are data, never SQL. Every identifier comes from a schema snapshot or a
validated generated column; values use psycopg parameters. Original source keys
and row identities travel as hidden columns through every transformation.
"""
import json
import re
from copy import deepcopy

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.serializers.json import DjangoJSONEncoder

from db_extraction.models import DatabaseSource, DatabaseTable
from db_extraction.services.postgres import connection_parameters
from .context import field_catalog

TYPES = {'text': 'text', 'integer': 'bigint', 'decimal': 'numeric',
         'date': 'date', 'datetime': 'timestamp', 'boolean': 'boolean', 'json': 'jsonb'}
OPERATORS = {'eq': '=', 'ne': '<>', 'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}
MAX_STEPS = 50
MAX_COLUMNS = 250


def fail(message):
    raise ValidationError(message)


def execution_error(error):
    """Explain source failures without disclosing credentials or source values."""
    if isinstance(error, psycopg.errors.QueryCanceled):
        return 'The source query timed out after 30 seconds. Add an earlier filter or simplify the merges.'
    if isinstance(error, psycopg.OperationalError):
        return 'The source connection is unavailable. Check the database connection and retry.'
    if isinstance(error, psycopg.DataError):
        return 'A type conversion or JSON expansion failed. Preview earlier Applied steps to locate the invalid value; check the selected type, locale separators, and JSON collection path.'
    return 'The source query could not run. Check matching column types and the saved schema. Refresh the schema if tables or columns have changed.'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', value):
        fail('Use a valid transformation identifier.')
    return value


def path_parts(path):
    from .database import json_path
    json_path({}, path, missing=True)
    return [part.replace('~1', '/').replace('~0', '~') for part in path.split('/')[1:]] if path else []


def dtype(column):
    value = column.type_name.lower()
    if value in {'json', 'jsonb'}:
        return 'json'
    if value == 'bool':
        return 'boolean'
    if value == 'date':
        return 'date'
    if 'timestamp' in value:
        return 'datetime'
    if value in {'int2', 'int4', 'int8'}:
        return 'integer'
    if value in {'numeric', 'float4', 'float8', 'money'}:
        return 'decimal'
    return 'text'


def col(ref, alias='p'):
    return sql.Identifier(alias, ref)


def condition(group, columns, params, depth=0):
    if depth > 15 or not isinstance(group, dict) or group.get('logic') not in {'all', 'any'} or not isinstance(group.get('children'), list) or not group['children']:
        fail('Add at least one valid filter condition.')
    if len(group['children']) > 50:
        fail('Use at most 50 conditions in a filter group.')
    parts = []
    for rule in group['children']:
        if not isinstance(rule, dict):
            fail('Choose a valid filter condition.')
        if 'children' in rule:
            parts.append(condition(rule, columns, params, depth+1))
            continue
        ref, op, value = rule.get('column'), rule.get('operator'), rule.get('value', '')
        if not isinstance(ref, str) or ref not in columns or not isinstance(op, str) or op not in {*OPERATORS, 'empty', 'not_empty', 'contains', 'starts', 'in'}:
            fail('Choose an available column and supported filter operation.')
        if not isinstance(value, (str, int, float, bool)) or len(str(value)) > 4000:
            fail('Filter values must be short scalar values.')
        expression = col(ref)
        if op in {'empty', 'not_empty'}:
            part = sql.SQL("({0} IS NULL OR {0}::text = '')").format(expression)
            parts.append(sql.SQL('NOT {}').format(part) if op == 'not_empty' else part)
        elif op in {'contains', 'starts'}:
            escaped = str(value).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params.append(('%' if op == 'contains' else '')+escaped+'%')
            parts.append(sql.SQL("{}::text ILIKE %s ESCAPE '\\'").format(expression))
        elif op == 'in':
            values = [part.strip() for part in str(value).split(',')]
            if len(values) > 100:
                fail('Use at most 100 values in an “is one of” filter.')
            params.extend(values)
            parts.append(sql.SQL('{} IN ({})').format(expression, sql.SQL(', ').join(sql.Placeholder() for _ in values)))
        else:
            if value == '':
                fail('Enter a filter value, or choose “is empty”.')
            params.append(value)
            parts.append(sql.SQL('{} {} %s').format(expression, sql.SQL(OPERATORS[op])))
    return sql.SQL('({})').format(sql.SQL(' AND ' if group['logic'] == 'all' else ' OR ').join(parts))


def validate(mode, record, query, complete=False):
    """Validate the recipe and compile each step into a CTE, in saved order."""
    from .database import primary_keys
    recipe = query.get('pipeline')
    if not isinstance(recipe, dict) or recipe.get('version') != 1 or not isinstance(recipe.get('steps'), list) or len(recipe['steps']) > MAX_STEPS:
        fail('Use a supported query builder recipe with at most 50 steps.')
    source = DatabaseSource.objects.filter(pk=query.get('database'), enabled=True).first()
    if not source:
        fail('Choose an enabled database connection.')
    base = DatabaseTable.objects.filter(pk=query.get('table'), schema__run__source=source, schema__run__status='completed').select_related('schema__run').prefetch_related('columns').first()
    if not base:
        fail('Choose a source table from this connection’s saved schema.')
    record.database_source = source
    tables, columns, hidden, identities, params, ctes = {'base': base}, {}, [], {}, [], []
    source_keys = recipe.get('sourceKeys', ['base.'+name for name in primary_keys(base)])
    if not isinstance(source_keys, list) or len(source_keys) > 8 or any(not isinstance(key, str) for key in source_keys) or len(set(source_keys)) != len(source_keys) or complete and not source_keys:
        fail('Choose one to eight source identifier columns. A primary key is suggested automatically.')
    base_columns = list(base.columns.all())
    selections = []
    for column in base_columns:
        ref = 'base.'+column.name
        if len(ref.encode()) > 63:
            fail('A source column name is too long for the query builder (maximum 58 bytes).')
        columns[ref] = {'id': ref, 'label': column.name, 'type': dtype(column), 'lineage': []}
        expression = sql.Identifier('src', column.name)
        if column.type_name == 'json':
            expression = sql.SQL('{}::jsonb').format(expression)
        selections.append(sql.SQL('{} AS {}').format(expression, sql.Identifier(ref)))
    for index, key in enumerate(source_keys):
        if key not in columns:
            fail('Source identifiers must be columns from the main table.')
        name = '__source_'+str(index)
        hidden.append(name)
        selections.append(sql.SQL('{} AS {}').format(sql.Identifier('src', key[5:]), sql.Identifier(name)))
    keys = list(hidden)
    ctes.append(sql.SQL('{} AS (SELECT {} FROM {} AS src)').format(sql.Identifier('q0'), sql.SQL(', ').join(selections), sql.Identifier(base.schema.name, base.name)))
    seen, sorts = set(), []

    def require(ref):
        if not isinstance(ref, str) or ref not in columns:
            fail('A step refers to a removed or unavailable column. Edit it or restore the earlier step.')
        return columns[ref]

    def projection(replacements=None, extra=None):
        replacements = replacements or {}
        return sql.SQL(', ').join([sql.SQL('{} AS {}').format(replacements.get(ref, col(ref)), sql.Identifier(ref)) for ref in columns] + [col(ref) for ref in hidden] + (extra or []))

    for index, step in enumerate(recipe['steps'], 1):
        if not isinstance(step, dict):
            fail('Each applied step must be an object.')
        sid = identifier(step.get('id'))
        if sid == 'base' or sid in seen:
            fail('Applied step identifiers must be unique.')
        seen.add(sid)
        name = step.get('name', step.get('type', 'Step'))
        if not isinstance(name, str) or len(name) > 100:
            fail('Step names must contain at most 100 characters.')
        kind = step.get('type')
        tail, replacements, extra, from_params, ordering_columns = sql.SQL(''), {}, [], [], []
        source_sql = sql.SQL('{} AS p').format(sql.Identifier('q'+str(index-1)))
        try:
            if kind == 'merge':
                related = DatabaseTable.objects.filter(pk=step.get('table'), schema__run=base.schema.run).select_related('schema').prefetch_related('columns').first()
                if not related or step.get('join', 'left') not in {'left', 'inner'}:
                    fail('Choose a related table in the same schema snapshot and a valid join type.')
                pairs = step.get('on')
                available = {column.name: column for column in related.columns.all()}
                if not isinstance(pairs, list) or not 1 <= len(pairs) <= 8:
                    fail('Choose matching columns for this merge.')
                matches = []
                for pair in pairs:
                    if not isinstance(pair, dict) or pair.get('right') not in available:
                        fail('Choose a valid matching column in the related table.')
                    require(pair.get('left'))
                    left, right = col(pair['left']), sql.Identifier('related', pair['right'])
                    if step.get('asText', False) is True:
                        left, right = sql.SQL('{}::text').format(left), sql.SQL('{}::text').format(right)
                    matches.append(sql.SQL('{} = {}').format(left, right))
                source_sql += sql.SQL(' {} JOIN {} AS related ON {}').format(sql.SQL('LEFT' if step.get('join', 'left') == 'left' else 'INNER'), sql.Identifier(related.schema.name, related.name), sql.SQL(' AND ').join(matches))
                selections = step.get('columns', list(available))
                if not isinstance(selections, list) or not selections or any(not isinstance(value, str) or value not in available for value in selections) or len(set(selections)) != len(selections):
                    fail('Choose the related columns to expand.')
                for value in selections:
                    ref = sid+'.'+value
                    if len(ref.encode()) > 63:
                        fail('A related column name is too long for this merge.')
                    columns[ref] = {'id': ref, 'label': related.name+'.'+value, 'type': dtype(available[value]), 'lineage': [sid]}
                    replacements[ref] = sql.Identifier('related', value)
                    if available[value].type_name == 'json':
                        replacements[ref] = sql.SQL('{}::jsonb').format(replacements[ref])
                identities[sid] = []
                for n, value in enumerate(primary_keys(related)):
                    ref = '__row_'+sid+'_'+str(n)
                    extra.append(sql.SQL('{} AS {}').format(sql.Identifier('related', value), sql.Identifier(ref)))
                    identities[sid].append(ref)
                tables[sid] = related
            elif kind == 'json_expand':
                original = require(step.get('column'))
                mode_json = step.get('mode', 'array')
                if mode_json not in {'array', 'record'}:
                    fail('Expand JSON as item rows or record fields.')
                from_params.append(path_parts(step.get('path', '')))
                # Blank values, JSON null, and empty objects yield an empty collection.
                value = sql.SQL("(NULLIF(BTRIM({}::text), '')::jsonb #> %s::text[])").format(col(step['column']))
                source_sql += sql.SQL(' CROSS JOIN LATERAL (SELECT {} AS value) AS document').format(value)
                if mode_json == 'array':
                    source_sql += sql.SQL(" LEFT JOIN LATERAL jsonb_array_elements(CASE WHEN document.value IS NULL OR document.value IN ('null'::jsonb, '{}'::jsonb) THEN '[]'::jsonb ELSE document.value END) WITH ORDINALITY AS item(value, ordinal) ON TRUE")
                    ref = '__row_'+sid+'_0'
                    extra.append(sql.SQL('item.ordinal AS {}').format(sql.Identifier(ref)))
                    identities[sid] = [ref]
                    item_value = sql.SQL('item.value')
                else:
                    item_value = sql.SQL('document.value')
                expanded = step.get('fields')
                if not isinstance(expanded, list) or not 1 <= len(expanded) <= 100:
                    fail('Choose one to 100 JSON fields to expand.')
                names = set()
                for field in expanded:
                    if not isinstance(field, dict) or not isinstance(field.get('name'), str) or not field['name'].strip() or len(field['name'].encode()) > 63 or field['name'] in names:
                        fail('Give each JSON field a unique name of at most 63 bytes.')
                    names.add(field['name'])
                    ref = sid+'.'+field['name']
                    if len(ref.encode()) > 63:
                        fail('Shorten the JSON output column name.')
                    params.append(path_parts(field.get('path', '')))
                    replacements[ref] = sql.SQL('{} #>> %s::text[]').format(item_value)
                    columns[ref] = {'id': ref, 'label': field['name'], 'type': 'text', 'lineage': original['lineage']+([sid] if mode_json == 'array' else [])}
            elif kind == 'select':
                keep = step.get('columns')
                if not isinstance(keep, list) or not keep or any(not isinstance(ref, str) for ref in keep) or len(set(keep)) != len(keep):
                    fail('Keep at least one column.')
                for ref in keep:
                    require(ref)
                columns = {ref: columns[ref] for ref in keep}
            elif kind == 'rename':
                require(step.get('column'))
                if not isinstance(step.get('label'), str) or not step['label'].strip() or len(step['label']) > 100:
                    fail('Enter a column name of at most 100 characters.')
                columns[step['column']] = {**columns[step['column']], 'label': step['label'].strip()}
            elif kind in {'type', 'trim', 'uppercase', 'replace'}:
                info = require(step.get('column'))
                expression = col(step['column'])
                if kind == 'type':
                    selected = step.get('dataType')
                    if selected not in TYPES:
                        fail('Choose a supported data type.')
                    expression = sql.SQL('{}::text' if selected == 'text' else "NULLIF(BTRIM({}::text), '')").format(expression)
                    if selected == 'decimal' and step.get('thousands', ''):
                        if step['thousands'] not in {',', '.', ' '}:
                            fail('Choose a supported thousands separator.')
                        params.append(step['thousands'])
                        expression = sql.SQL("replace({}, %s, '')").format(expression)
                    if selected == 'decimal' and step.get('decimal', '.') == ',':
                        if step.get('thousands') == ',':
                            fail('Decimal and thousands separators must be different.')
                        expression = sql.SQL("replace({}, ',', '.')").format(expression)
                    fmt = step.get('dateFormat', 'YYYY-MM-DD')
                    if fmt not in {'YYYY-MM-DD', 'DD/MM/YYYY', 'MM/DD/YYYY'}:
                        fail('Choose a supported source date format.')
                    if selected == 'date' and fmt in {'DD/MM/YYYY', 'MM/DD/YYYY'}:
                        # Build an ISO date and let PostgreSQL reject invalid dates.
                        order = (3, 2, 1) if fmt == 'DD/MM/YYYY' else (3, 1, 2)
                        expression = sql.SQL("CASE WHEN {0} IS NULL THEN NULL ELSE concat_ws('-', split_part({0}, '/', {1}), split_part({0}, '/', {2}), split_part({0}, '/', {3})) END").format(expression, *(sql.Literal(n) for n in order))
                    # Casting decimal to bigint rounds; text-to-bigint rejects fractions.
                    expression = sql.SQL('({})::{}').format(expression, sql.SQL(TYPES[selected]))
                    columns[step['column']] = {**info, 'type': selected}
                elif kind == 'trim':
                    expression = sql.SQL('BTRIM({}::text)').format(expression)
                    columns[step['column']] = {**info, 'type': 'text'}
                elif kind == 'uppercase':
                    expression = sql.SQL('UPPER({}::text)').format(expression)
                    columns[step['column']] = {**info, 'type': 'text'}
                else:
                    if any(not isinstance(step.get(key), str) or len(step[key]) > 4000 for key in ('find', 'replacement')):
                        fail('Enter text to find and its replacement.')
                    params.extend([step['find'], step['replacement']])
                    expression = sql.SQL('replace({}::text, %s, %s)').format(expression)
                    columns[step['column']] = {**info, 'type': 'text'}
                replacements[step['column']] = expression
            elif kind == 'filter':
                tail = sql.SQL(' WHERE {}').format(condition(step.get('rules'), columns, params))
            elif kind == 'sort':
                values = step.get('sorts')
                if not isinstance(values, list) or not 1 <= len(values) <= 8:
                    fail('Choose one to eight sort columns.')
                for value in values:
                    if not isinstance(value, dict) or value.get('direction') not in {'asc', 'desc'}:
                        fail('Choose ascending or descending order.')
                    require(value.get('column'))
                # Capture the ordering at this point. A later conversion or
                # column removal must not reinterpret an earlier sort.
                ordering = [sql.SQL('{} {} NULLS LAST').format(col(value['column']), sql.SQL(value['direction'].upper())) for value in values]
                ordering += [col(value['column']) for value in sorts] + [col(ref) for ref in hidden]
                ref = '__sort_'+sid
                extra.append(sql.SQL('row_number() OVER (ORDER BY {}) AS {}').format(sql.SQL(', ').join(ordering), sql.Identifier(ref)))
                ordering_columns.append(ref)
                sorts = [{'column': ref, 'direction': 'asc'}]
            elif kind == 'deduplicate':
                values = step.get('columns') or list(columns)
                if not isinstance(values, list) or not values:
                    fail('Choose columns to compare for duplicates.')
                for ref in values:
                    require(ref)
                unique = list(dict.fromkeys(keys+values))
                compared = sql.SQL(', ').join(col(ref) for ref in unique)
                ordered = sql.SQL(', ').join(col(ref) for ref in dict.fromkeys(unique+[item['column'] for item in sorts]+hidden))
                statement = sql.SQL('SELECT DISTINCT ON ({}) {} FROM {} ORDER BY {}').format(compared, projection(), source_sql, ordered)
                ctes.append(sql.SQL('{} AS ({})').format(sql.Identifier('q'+str(index)), statement))
                continue
            else:
                fail('Choose a supported transformation step.')
            statement = sql.SQL('SELECT {} FROM {}{}').format(projection(replacements, extra), source_sql, tail)
            params.extend(from_params)
            ctes.append(sql.SQL('{} AS ({})').format(sql.Identifier('q'+str(index)), statement))
            hidden.extend(identities.get(sid, [])+ordering_columns)
            if len(columns) > MAX_COLUMNS:
                fail('Keep at most 250 preview columns. Add Choose columns before expanding more data.')
        except ValidationError as error:
            fail('Step '+str(index)+' (“'+name+'”): '+'; '.join(error.messages))

    if len(columns) > MAX_COLUMNS:
        fail('Keep at most 250 prepared columns. Add Choose columns before previewing or matching fields.')
    mappings = query.get('mappings', [])
    allowed = {field['id']: field for field in field_catalog(mode, record.target_entity)}
    if not isinstance(mappings, list) or len(mappings) > len(allowed):
        fail('Choose supported accounting field mappings.')
    mapped, lineage = {}, set()
    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get('id'), str) or mapping.get('id') not in allowed or mapping['id'] in mapped or type(mapping.get('include')) is not bool:
            fail('Map each supported accounting field once.')
        if mapping.get('id') == 'line:line_no' and mapping.get('method') == 'sequence':
            mapping['method'] = 'number'
        if mapping.get('method') not in {'column', 'empty', 'value', 'number'} or mapping.get('transform', 'identity') != 'identity':
            fail('Apply conversions in Applied steps before matching accounting fields.')
        mapped[mapping['id']] = mapping
        if not mapping['include']:
            continue
        if mapping['method'] == 'column':
            if complete or mapping.get('column') in columns:
                info = require(mapping.get('column'))
                if mapping['id'].startswith('line:') and mapping['id'] != 'line:line_no':
                    lineage.update(info['lineage'])
        elif mapping['method'] == 'number' and mapping['id'] != 'line:line_no':
            fail('Automatic numbering is available for line numbers only.')
        elif mapping['method'] == 'value' and not isinstance(mapping.get('value'), (str, int, float, bool, type(None))):
            fail('Accounting default values must be scalar values.')
    if complete:
        for ref, field in allowed.items():
            item = mapped.get(ref, {})
            if field['required'] and (not item.get('include') or item.get('method') == 'empty' or item.get('method') == 'value' and item.get('value') in ('', None)):
                fail('Match required accounting field '+field['label']+'.')
        if any(not identities.get(sid) for sid in lineage):
            fail('Related line-item tables need primary keys to preserve repeated rows.')
    query['keys'] = keys
    return {'tables': tables, 'source': source, 'keys': keys, 'key_names': [key[5:] for key in source_keys],
            'output_columns': list(columns.values()), 'hidden': hidden, 'identities': identities,
            'line_keys': [key for sid in sorted(lineage) for key in identities.get(sid, [])],
            'ctes': ctes, 'params': params, 'sorts': sorts, 'last': 'q'+str(len(recipe['steps'])), 'pipeline': True}


def compile_query(query, metadata, bounded=True, preview=False, limit=50, offset=0):
    params = list(metadata['params'])
    if preview:
        references = [value['id'] for value in metadata['output_columns']]+metadata['hidden']
    else:
        # Do not transfer a whole JSON document once for every expanded item.
        # Accounting needs only mapped values and immutable record/item IDs.
        references = [mapping['column'] for mapping in query.get('mappings', []) if mapping.get('include') and mapping.get('method') == 'column']+metadata['keys']+metadata['line_keys']
    selections = [col(ref) for ref in dict.fromkeys(references)]
    order = [sql.SQL('{} {} NULLS LAST').format(col(item['column']), sql.SQL(item['direction'].upper())) for item in metadata['sorts']]
    stable = [col(ref) for ref in metadata['hidden']]
    # Accounting streams group complete source records; the shaping grid follows
    # the user's sort first and pages entirely at PostgreSQL.
    order = order+stable if preview else [col(ref) for ref in metadata['keys']]+order+stable
    statement = sql.SQL('WITH {} SELECT {} FROM {} AS p').format(sql.SQL(', ').join(metadata['ctes']), sql.SQL(', ').join(selections), sql.Identifier(metadata['last']))
    if order:
        statement += sql.SQL(' ORDER BY {}').format(sql.SQL(', ').join(order))
    if bounded:
        statement += sql.SQL(' LIMIT %s OFFSET %s')
        params.extend([limit+1, offset])
    return statement, params, metadata['line_keys']


def preview(mode, record, step=None, limit=50, offset=0):
    if type(limit) is not int or limit not in {25, 50, 100} or type(offset) is not int or not 0 <= offset <= 1000000:
        fail('Preview 25, 50, or 100 rows at a valid page offset.')
    query = deepcopy(record.setup_data['database'])
    steps = query.get('pipeline', {}).get('steps', [])
    if step is None:
        step = len(steps)
    if type(step) is not int or not 0 <= step <= len(steps):
        fail('Choose an applied step to preview.')
    query['pipeline']['steps'] = steps[:step]
    query['mappings'] = []  # Browsing does not depend on accounting requirements.
    metadata = validate(mode, record, query)
    statement, params, _ = compile_query(query, metadata, preview=True, limit=limit, offset=offset)
    try:
        with psycopg.connect(**connection_parameters(metadata['source']), row_factory=dict_row) as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            rows = connection.execute(statement, params).fetchall()
    except psycopg.Error as error:
        fail(execution_error(error))
    except ImproperlyConfigured:
        fail('The saved credential encryption key is unavailable.')
    visible = [{column['id']: row.get(column['id']) for column in metadata['output_columns']} for row in rows[:limit]]
    payload = {'columns': metadata['output_columns'], 'rows': visible, 'has_more': len(rows)>limit,
               'offset': offset, 'limit': limit, 'step': step, 'read_only': True}
    encoded = json.dumps(payload, cls=DjangoJSONEncoder)
    if len(encoded.encode()) > 4*1024*1024:
        fail('The preview exceeds 4 MiB. Choose fewer columns or add an earlier filter.')
    return json.loads(encoded)
