"""Compile reviewed mappings into read-only PostgreSQL previews and streamed migrations."""
import json
import re
from itertools import groupby, islice
from collections import OrderedDict

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.serializers.json import DjangoJSONEncoder

from db_extraction.models import DatabaseSource, DatabaseTable
from db_extraction.services.postgres import connection_parameters
from .context import field_catalog
from .configuration import clean_output

MAX_ROWS = 5000
COMPARISONS = {'eq': '=', 'ne': '<>', 'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}


def primary_keys(table):
    constraint = table.constraints.filter(constraint_type='primary_key').first()
    return list(constraint.columns.order_by('position').values_list('column__name', flat=True)) if constraint else []


def validate_query(mode, record, query, complete=False):
    if not isinstance(query, dict):
        raise ValidationError('Provide a structured database query.')
    if 'pipeline' in query:
        from .pipeline import validate
        return validate(mode, record, query, complete)
    source_id = query.get('database')
    if not source_id:
        if complete:
            raise ValidationError('Choose a database connection.')
        return None
    source = DatabaseSource.objects.filter(pk=source_id, enabled=True).first()
    if not source:
        raise ValidationError('Choose an enabled database connection.')
    record.database_source = source
    if not query.get('table'):
        if complete:
            raise ValidationError('Choose a table and column beside a field mapping.')
        return None
    table = DatabaseTable.objects.filter(pk=query['table'], schema__run__source=source, schema__run__status='completed').select_related('schema__run').prefetch_related('columns').first()
    if table is None:
        raise ValidationError('Choose a table from the selected connection’s completed schema snapshot.')
    tables, columns = {'base': table}, {'base': set(table.columns.values_list('name', flat=True))}
    joins = query.get('joins', [])
    if not isinstance(joins, list):
        raise ValidationError('Table connections must be a list.')
    for join in joins:
        if not isinstance(join, dict) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', str(join.get('id', ''))) or join['id'] in tables or join.get('type') not in {'left', 'inner'}:
            raise ValidationError('Choose a valid table connection and match type.')
        related = DatabaseTable.objects.filter(pk=join.get('table'), schema__run=table.schema.run).select_related('schema').prefetch_related('columns').first()
        if related is None:
            raise ValidationError('All connected tables must belong to the same source snapshot.')
        pairs = join.get('on')
        if not isinstance(pairs, list):
            raise ValidationError('Provide matching columns for each table connection.')
        target_columns = set(related.columns.values_list('name', flat=True))
        if complete and not pairs:
            raise ValidationError('Complete the matching columns for '+str(related)+'.')
        for pair in pairs:
            if not isinstance(pair, dict):
                raise ValidationError('Invalid matching columns.')
            if pair.get('left') or pair.get('right') or complete:
                validate_reference(pair.get('left'), columns)
                if pair.get('right') not in target_columns:
                    raise ValidationError('Choose the matching column in '+str(related)+'.')
        tables[join['id']], columns[join['id']] = related, target_columns
    keys = query.get('keys', [])
    if not isinstance(keys, list):
        raise ValidationError('Row identifiers must be a list.')
    if query.get('keyMode', 'auto') == 'auto':
        keys = ['base.'+key for key in primary_keys(table)]
        query['keys'] = keys
    if complete and not keys:
        raise ValidationError('This table has no primary key. Choose custom Table → Column identifiers in Advanced row identification.')
    for reference in keys:
        if reference or complete:
            validate_reference(reference, columns)
    allowed = {field['id']: field for field in field_catalog(mode, record.target_entity)}
    mappings = query.get('mappings', [])
    if not isinstance(mappings, list) or any(not isinstance(item, dict) for item in mappings):
        raise ValidationError('Provide field mappings.')
    if len({item.get('id') for item in mappings}) != len(mappings):
        raise ValidationError('Map each destination field only once.')
    mapped = {}
    for item in mappings:
        # Older saved setups called automatic line numbering "sequence". Normalize
        # even excluded fields, which still pass through mapping validation.
        if item.get('id') == 'line:line_no':
            if (item.get('method') == 'sequence'
                    or item.get('method') == 'column' and not item.get('column')
                    or item.get('method') == 'value' and item.get('value') in ('', None)):
                item['method'] = 'number'
        if item.get('id') not in allowed or item.get('method') not in {'column', 'value', 'empty', 'json', 'number'} or type(item.get('include')) is not bool:
            raise ValidationError('Choose supported destination fields and mapping methods.')
        if item.get('transform', 'identity') not in {'identity', 'trim', 'uppercase', 'json', 'date', 'datetime', 'decimal', 'integer', 'boolean', 'lookup'}:
            raise ValidationError('Choose a supported value conversion.')
        mapped[item['id']] = item
        if not item['include']:
            continue
        if item['method'] in {'column', 'json'} and (item.get('column') or complete):
            validate_reference(item.get('column'), columns)
        if item['method'] == 'number' and item['id'] != 'line:line_no':
            raise ValidationError('Automatic numbering is available only for line numbers.')
        if item['method'] == 'json':
            json_path({}, item.get('path', ''), missing=True)
        if item['method'] == 'value' and not isinstance(item.get('value'), (str, int, float, bool, type(None))):
            raise ValidationError('Approved values must be scalar values.')
    if complete:
        for key, field in allowed.items():
            item = mapped.get(key, {})
            if field['required'] and (not item.get('include') or item.get('method') == 'empty' or item.get('method') == 'value' and item.get('value') in ('', None)):
                raise ValidationError('Map required field '+field['label']+'.')
        if not any(item.get('include') for item in mappings):
            raise ValidationError('Include at least one output field.')
    collection = query.get('lineItems')
    if collection:
        if not isinstance(collection, dict):
            raise ValidationError('Choose a JSON column for line items.')
        validate_reference(collection.get('column'), columns)
        json_path({}, collection.get('path', ''), missing=True)
        if any(mapping['include'] and mapping['method'] == 'json' and mapping['id'].startswith('line:') and mapping.get('column') != collection['column'] for mapping in mappings):
            raise ValidationError('JSON line fields must use the selected item collection column.')
    check_group(query.get('filters', {'logic': 'all', 'children': []}), columns, complete)
    if not isinstance(query.get('sorts', []), list):
        raise ValidationError('Sorting must be a list.')
    for sort in query.get('sorts', []):
        if not isinstance(sort, dict) or sort.get('direction') not in {'asc', 'desc'}:
            raise ValidationError('Choose a supported sort direction.')
        if sort.get('column') or complete:
            validate_reference(sort.get('column'), columns)
    if type(query.get('distinct', False)) is not bool:
        raise ValidationError('Choose whether duplicate output rows should be removed.')
    return {'tables': tables, 'columns': columns, 'source': source, 'keys': keys}


def validate_reference(reference, columns):
    if not isinstance(reference, str) or '.' not in reference:
        raise ValidationError('Choose a table and column for every mapping, condition, and identifier.')
    alias, column = reference.split('.', 1)
    if alias not in columns or column not in columns[alias]:
        raise ValidationError('The selected column is not in this query’s saved schema.')
    return alias, column


def check_group(group, columns, complete, depth=0):
    if depth > 30 or not isinstance(group, dict) or group.get('logic') not in {'all', 'any'} or not isinstance(group.get('children'), list):
        raise ValidationError('Use valid AND/OR condition groups (maximum nesting depth 30).')
    if complete and depth and not group['children']:
        raise ValidationError('Add a condition to the empty group or remove it.')
    for rule in group['children']:
        if not isinstance(rule, dict):
            raise ValidationError('Invalid row condition.')
        if 'children' in rule:
            check_group(rule, columns, complete, depth+1)
        else:
            if rule.get('operator') not in {*COMPARISONS, 'contains', 'starts', 'in', 'empty', 'not_empty'}:
                raise ValidationError('Choose a supported comparison.')
            if rule.get('column') or complete:
                validate_reference(rule.get('column'), columns)
            if not isinstance(rule.get('value', ''), (str, int, float, bool)):
                raise ValidationError('Condition values must be scalar values.')
            if complete and rule['operator'] not in {'empty', 'not_empty'} and rule.get('value') in ('', None):
                raise ValidationError('Enter a value for each row condition.')


def reference_sql(reference):
    return sql.Identifier(*reference.split('.', 1))


def where_sql(group, params):
    parts = []
    for rule in group['children']:
        if 'children' in rule:
            parts.append(where_sql(rule, params))
            continue
        column, operator = reference_sql(rule['column']), rule['operator']
        if operator in {'empty', 'not_empty'}:
            part = sql.SQL('({0} IS NULL OR {0}::text = \'\')').format(column)
            parts.append(sql.SQL('NOT {}').format(part) if operator == 'not_empty' else part)
        elif operator in {'contains', 'starts'}:
            escaped = str(rule['value']).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params.append(('%' if operator == 'contains' else '')+escaped+'%')
            parts.append(sql.SQL("{}::text ILIKE %s ESCAPE '\\'").format(column))
        elif operator == 'in':
            values = [value.strip() for value in str(rule['value']).split(',')]
            params.extend(values)
            parts.append(sql.SQL('{} IN ({})').format(column, sql.SQL(', ').join(sql.Placeholder() for _ in values)))
        else:
            params.append(rule['value'])
            parts.append(sql.SQL('{} {} %s').format(column, sql.SQL(COMPARISONS[operator])))
    return sql.SQL('({})').format(sql.SQL(' AND ' if group['logic'] == 'all' else ' OR ').join(parts)) if parts else sql.SQL('TRUE')


def compile_query(query, metadata, bounded=True):
    """Only server-validated metadata identifiers enter SQL; user values stay parameters."""
    if metadata.get('pipeline'):
        from .pipeline import compile_query as compile_pipeline
        return compile_pipeline(query, metadata, bounded=bounded, limit=MAX_ROWS)
    tables, needed = metadata['tables'], set(metadata['keys'])
    for mapping in query['mappings']:
        if mapping['include'] and mapping['method'] in {'column', 'json'}:
            needed.add(mapping['column'])
    if query.get('lineItems'):
        needed.add(query['lineItems']['column'])
    line_aliases = {item['column'].split('.', 1)[0] for item in query['mappings'] if item['include'] and item['method'] == 'column' and item['id'].startswith('line:')}
    line_keys = [alias+'.'+key for alias in sorted(line_aliases) for key in primary_keys(tables[alias])]
    if line_aliases and any(not primary_keys(tables[alias]) for alias in line_aliases):
        raise ValidationError('Line-item source tables need primary keys to preserve repeated item rows accurately.')
    needed.update(line_keys)
    needed.update(alias+'.'+key for alias, table in tables.items() for key in primary_keys(table))
    base = tables['base']
    statement = sql.SQL('SELECT {} FROM {} AS {}').format(sql.SQL(', ').join(sql.SQL('{} AS {}').format(reference_sql(ref), sql.Identifier(ref)) for ref in sorted(needed)), sql.Identifier(base.schema.name, base.name), sql.Identifier('base'))
    for join in query.get('joins', []):
        table = tables[join['id']]
        statement += sql.SQL(' {} JOIN {} AS {} ON {}').format(sql.SQL('LEFT' if join['type'] == 'left' else 'INNER'), sql.Identifier(table.schema.name, table.name), sql.Identifier(join['id']), sql.SQL(' AND ').join(sql.SQL('{} = {}').format(reference_sql(pair['left']), sql.Identifier(join['id'], pair['right'])) for pair in join['on']))
    params = []
    statement += sql.SQL(' WHERE {}').format(where_sql(query.get('filters', {'logic': 'all', 'children': []}), params))
    sorts = [sql.SQL('{} {} NULLS LAST').format(reference_sql(item['column']), sql.SQL(item['direction'].upper())) for item in query.get('sorts', [])]
    # A complete record must remain contiguous while a large result is streamed.
    sorts = [reference_sql(ref) for ref in metadata['keys']] + sorts + [reference_sql(ref) for ref in line_keys]
    statement += sql.SQL(' ORDER BY {}').format(sql.SQL(', ').join(sorts))
    if bounded:
        statement += sql.SQL(' LIMIT %s')
        params.append(MAX_ROWS+1)
    return statement, params, line_keys


def fetch(query, metadata):
    statement, params, line_keys = compile_query(query, metadata)
    try:
        with psycopg.connect(**connection_parameters(metadata['source']), row_factory=dict_row) as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            rows = connection.execute(statement, params).fetchall()
    except psycopg.Error:
        raise ValidationError('The read-only query failed. Check column types, connection permissions, and the saved schema.') from None
    if len(rows) > MAX_ROWS:
        raise ValidationError('This query exceeds the 5,000 source-row preview/import bound. Add filters or refine the table connections.')
    return rows, line_keys


def json_path(value, path, missing=False, optional=False):
    if not isinstance(path, str) or path and not path.startswith('/') or len(path) > 1000 or len(path.split('/')) > 33 or re.search(r'~(?![01])', path):
        raise ValidationError('Use a valid JSON pointer, such as /DATA or /MODEL.')
    if missing:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValidationError('The source value is not valid JSON. Choose a conversion or correct the source.') from None
    for part in path.split('/')[1:] if path else []:
        part = part.replace('~1', '/').replace('~0', '~')
        try:
            value = value[int(part)] if isinstance(value, list) and part.isdecimal() else value[part]
        except (KeyError, IndexError, TypeError):
            if optional:
                return None
            raise ValidationError('JSON field '+path+' is missing. Correct its mapping.') from None
    return value


def item_rows(value, path):
    if value is None or value == '' or isinstance(value, str) and not value.strip():
        return []
    value = json_path(value, '')
    if value is None or value == '' or value == {} or value == []:
        return []
    value = json_path(value, path)
    if value is None or value == '' or value == {}:
        return []
    if isinstance(value, dict) and len(value) == 1 and isinstance(next(iter(value.values())), list):
        value = next(iter(value.values()))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValidationError('The JSON item collection must be an array of objects. Select its collection path.')
    if len(value) > 1000:
        raise ValidationError('A record exceeds 1,000 JSON line items.')
    return value


def grouped(mode, record, query, source_rows, line_keys):
    mappings = [item for item in query['mappings'] if item['include']]
    has_lines = any(item['id'].startswith('line:') and item['id'] != 'line:line_no' and item['method'] != 'empty' for item in mappings)
    result, issues, duplicate_count = OrderedDict(), [], 0
    collection = query.get('lineItems') if has_lines else None
    expanded = []
    if collection:
        seen = set()
        for raw in source_rows:
            used = {*query['keys'], collection['column'], *[mapping['column'] for mapping in mappings if mapping['id'].startswith('header:') and mapping['method'] in {'column', 'json'}]}
            identity = json.dumps({ref: raw.get(ref) for ref in used}, cls=DjangoJSONEncoder, sort_keys=True)
            if identity in seen:
                continue
            seen.add(identity)
            items = item_rows(raw.get(collection['column']), collection.get('path', ''))
            for index, item in enumerate(items, 1):
                expanded.append((raw, item, index))
            if not items:
                expanded.append((raw, None, 0))
    else:
        expanded = [(raw, None, index) for index, raw in enumerate(source_rows, 1)]
    for raw, json_item, index in expanded:
        key = tuple(raw[ref] for ref in query['keys'])
        if any(value is None for value in key):
            issues.append('A result row has an empty identifier.')
        mapped = {mapping['id']: raw.get(mapping['column']) if mapping['method'] == 'column' else
                  json_path(json_item if collection and mapping['id'].startswith('line:') else raw.get(mapping['column']), mapping.get('path', ''), optional=mapping['id'].startswith('line:')) if mapping['method'] == 'json' and (not collection or json_item is not None) else
                  (index if collection else len(result.get(key, {}).get('lines', []))+1) if mapping['method'] == 'number' else mapping.get('value') if mapping['method'] == 'value' else None for mapping in mappings}
        for item in mappings:
            value = mapped[item['id']]
            if value is None:
                continue
            if isinstance(value, (dict, list)) and item.get('transform') in {'trim', 'uppercase'}:
                raise ValidationError(item['id']+' contains structured JSON. Map a scalar field before applying text conversions.')
            if item.get('transform') == 'trim':
                mapped[item['id']] = str(value).strip()
            elif item.get('transform') == 'uppercase':
                mapped[item['id']] = str(value).strip().upper()
            elif item.get('transform') == 'json' and isinstance(value, str):
                try:
                    mapped[item['id']] = json.loads(value)
                except ValueError:
                    raise ValidationError('The mapped source value is not valid JSON.') from None
        header = {name: value for name, value in mapped.items() if name.startswith('header:')}
        line = {name: value for name, value in mapped.items() if name.startswith('line:')}
        if key not in result:
            result[key] = {'header': header, 'lines': [], 'raw': raw, 'line_keys': set()}
        else:
            if result[key]['header'] != header:
                issues.append('One record identifier produces different header values. Refine its related-table matches.')
            # Prepared rows may repeat a header after a merge/JSON expansion.
            # The original source identity defines one accounting record even
            # when the user deliberately supplies no optional item fields.
            if not has_lines and not query.get('pipeline') and (not query.get('distinct') or result[key]['header'] != header):
                duplicate_count += 1
        if has_lines and any(value not in (None, '') for name,value in line.items() if name != 'line:line_no') and (not collection or json_item is not None):
            identity = (index, json.dumps(raw, cls=DjangoJSONEncoder, sort_keys=True)) if collection else tuple(raw.get(ref) for ref in line_keys) if line_keys else json.dumps(line, cls=DjangoJSONEncoder, sort_keys=True)
            if line_keys and not query.get('pipeline') and any(value is None for value in identity):
                issues.append('A line item has no matched source identifier.')
            if identity not in result[key]['line_keys']:
                result[key]['line_keys'].add(identity)
                if len(result[key]['lines']) >= 1000:
                    issues.append('A record exceeds 1,000 line items. Refine its joins or item collection.')
                else:
                    result[key]['lines'].append(line)
    if duplicate_count:
        issues.append(f'{duplicate_count} extra row(s) share an identifier. Refine the matches or enable exact duplicate removal.')
    return list(result.values()), list(dict.fromkeys(issues)), duplicate_count


def stream_records(mode, record, include_raw=False):
    """Read every matching identity in one source snapshot, without a dataset cap."""
    query = record.setup_data['database']
    metadata = validate_query(mode, record, query, complete=True)
    statement, params, line_keys = compile_query(query, metadata, bounded=False)
    try:
        with psycopg.connect(**connection_parameters(metadata['source']), row_factory=dict_row) as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            with connection.cursor(name='bizmatic_migration_review') as cursor:
                cursor.itersize = 250
                cursor.execute(statement, params)
                for key, source_group in groupby(cursor, key=lambda row: tuple(row[ref] for ref in metadata['keys'])):
                    raw, size, oversized = [], 0, False
                    for row in source_group:
                        size += len(json.dumps(row, cls=DjangoJSONEncoder).encode())
                        if len(raw) >= MAX_ROWS or size > 8*1024*1024:
                            oversized = True
                        elif not oversized:
                            raw.append(row)
                    identity = dict(zip(metadata.get('key_names', [ref.removeprefix('base.') for ref in metadata['keys']]), key))
                    try:
                        if oversized:
                            raise ValidationError('This record exceeds 5,000 joined rows or 8 MiB. Refine its joins or selected fields.')
                        rows, issues, _ = grouped(mode, record, query, raw, line_keys)
                        row = rows[0]
                        parsed = {'record': {name.split(':', 1)[1]: value for name, value in row['header'].items()},
                                  'lines': [{name.split(':', 1)[1]: value for name, value in line.items()} for line in row['lines']], 'issues': issues}
                        yield (identity, parsed, raw) if include_raw else (identity, parsed)
                    except (ValidationError, ValueError, TypeError) as error:
                        parsed = {'record': {}, 'lines': [], 'issues': error.messages if isinstance(error, ValidationError) else [str(error)]}
                        yield (identity, parsed, raw) if include_raw else (identity, parsed)
    except psycopg.Error as error:
        if metadata.get('pipeline'):
            from .pipeline import execution_error
            raise ValidationError(execution_error(error)+' No accounting data has been saved.') from None
        raise ValidationError('The read-only migration query failed or timed out. No accounting data has been saved. Review the connection and query, then retry.') from None
    except ImproperlyConfigured:
        raise ValidationError('The saved database credential key is unavailable. Restore it before reviewing or migrating records.') from None


def read_rows(mode, record):
    query = record.setup_data['database']
    metadata = validate_query(mode, record, query, complete=True)
    source_rows, line_keys = fetch(query, metadata)
    records, issues, duplicates = grouped(mode, record, query, source_rows, line_keys)
    return query, metadata, records, issues, duplicates


def test(mode, record, limit):
    if type(limit) is not int or limit not in {5, 10, 25}:
        raise ValidationError('Preview 5, 10, or 25 records.')
    query = record.setup_data['database']
    metadata = validate_query(mode, record, query, complete=True)
    iterator = stream_records(mode, record, include_raw=True)
    try:
        preview = list(islice(iterator, limit+1))
    finally:
        iterator.close()
    shown, issues = preview[:limit], []
    for key, output, raw in shown:
        issues.extend('Source '+json.dumps(key, cls=DjangoJSONEncoder)+': '+message for message in clean_output(mode, record, output))
    if not shown:
        issues.append('No matching records. Adjust the row conditions before migration.')
    raw_columns = shown[0][2][0] if shown and shown[0][2] else {}
    source_headers = ([column for column in metadata['output_columns'] if column['id'] in raw_columns]
                      if metadata.get('pipeline') else
                      [{'id': ref, 'label': str(metadata['tables'][ref.split('.', 1)[0]])+'.'+ref.split('.', 1)[1]} for ref in raw_columns])
    return {'passed': not issues, 'issues': list(dict.fromkeys(issues)), 'count': len(shown), 'has_more': len(preview)>limit, 'duplicateCount': 0,
            'rows': [{**{'header:'+key:value for key,value in output['record'].items()}, **{'line:'+key:value for key,value in line.items()}} for _, output, _ in shown for line in (output['lines'] or [{}])][:100],
            'rawRows': [row for _, _, raw in shown for row in raw[:1]],
            'headers': [{'id': item['id'], 'label': next(field['label'] for field in field_catalog(mode, record.target_entity) if field['id'] == item['id'])} for item in query['mappings'] if item['include']],
            'sourceHeaders': source_headers}


def import_rows(mode, record, limit, offset):
    # Legacy read-only sample tools still use this interface. Fetch only their
    # requested window rather than materializing a whole dataset for one sample.
    iterator = stream_records(mode, record)
    try:
        rows = list(islice(iterator, offset, offset+limit))
    finally:
        iterator.close()
    issues = [issue for _, parsed in rows for issue in parsed['issues']]
    if issues:
        raise ValidationError(issues)
    return [({**{'header:'+name:value for name,value in parsed['record'].items()}, **key},
             [{'line:'+name:value for name,value in line.items()} for line in parsed['lines']]) for key, parsed in rows]
