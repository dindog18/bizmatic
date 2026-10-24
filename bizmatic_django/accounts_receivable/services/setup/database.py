"""Compile reviewed table/column choices into bounded, parameterized read-only PostgreSQL queries."""
import json
import re
from collections import OrderedDict

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from django.core.exceptions import ValidationError
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
        if item.get('id') not in allowed or item.get('method') not in {'column', 'value', 'empty'} or type(item.get('include')) is not bool:
            raise ValidationError('Choose supported destination fields and mapping methods.')
        if item.get('transform', 'identity') not in {'identity', 'trim', 'uppercase', 'json', 'date', 'datetime', 'decimal', 'integer', 'boolean', 'lookup'}:
            raise ValidationError('Choose a supported value conversion.')
        mapped[item['id']] = item
        if not item['include']:
            continue
        if item['method'] == 'column' and (item.get('column') or complete):
            validate_reference(item.get('column'), columns)
        if item['method'] == 'value' and not isinstance(item.get('value'), (str, int, float, bool, type(None))):
            raise ValidationError('Approved values must be scalar values.')
    if complete:
        for key, field in allowed.items():
            item = mapped.get(key, {})
            if field['required'] and (not item.get('include') or item.get('method') == 'empty' or item.get('method') == 'value' and item.get('value') in ('', None)):
                raise ValidationError('Map required field '+field['label']+'.')
        if not any(item.get('include') for item in mappings):
            raise ValidationError('Include at least one output field.')
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


def compile_query(query, metadata):
    """Only server-validated metadata identifiers enter SQL; user values stay parameters."""
    tables, needed = metadata['tables'], set(metadata['keys'])
    for mapping in query['mappings']:
        if mapping['include'] and mapping['method'] == 'column':
            needed.add(mapping['column'])
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
    sorts += [reference_sql(ref) for ref in metadata['keys']+line_keys]
    statement += sql.SQL(' ORDER BY {} LIMIT %s').format(sql.SQL(', ').join(sorts))
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


def grouped(mode, record, query, source_rows, line_keys):
    mappings = [item for item in query['mappings'] if item['include']]
    has_lines = any(item['id'].startswith('line:') and item['method'] != 'empty' for item in mappings)
    result, issues, duplicate_count = OrderedDict(), [], 0
    for raw in source_rows:
        key = tuple(raw[ref] for ref in query['keys'])
        if any(value is None for value in key):
            issues.append('A result row has an empty identifier.')
        mapped = {item['id']: raw.get(item['column']) if item['method'] == 'column' else item.get('value') if item['method'] == 'value' else None for item in mappings}
        for item in mappings:
            value = mapped[item['id']]
            if value is None:
                continue
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
            if not has_lines and (not query.get('distinct') or result[key]['header'] != header):
                duplicate_count += 1
        if has_lines and line:
            identity = tuple(raw.get(ref) for ref in line_keys) if line_keys else json.dumps(line, cls=DjangoJSONEncoder, sort_keys=True)
            if line_keys and any(value is None for value in identity):
                issues.append('A line item has no matched source identifier.')
            if identity not in result[key]['line_keys']:
                result[key]['line_keys'].add(identity)
                result[key]['lines'].append(line)
    if duplicate_count:
        issues.append(f'{duplicate_count} extra row(s) share an identifier. Refine the matches or enable exact duplicate removal.')
    return list(result.values()), list(dict.fromkeys(issues)), duplicate_count


def read_rows(mode, record):
    query = record.setup_data['database']
    metadata = validate_query(mode, record, query, complete=True)
    source_rows, line_keys = fetch(query, metadata)
    records, issues, duplicates = grouped(mode, record, query, source_rows, line_keys)
    return query, metadata, records, issues, duplicates


def test(mode, record, limit):
    if type(limit) is not int or limit not in {5, 10, 25}:
        raise ValidationError('Preview 5, 10, or 25 records.')
    query, metadata, records, issues, duplicates = read_rows(mode, record)
    for item in records:
        output = {'record': {key.split(':', 1)[1]: value for key, value in item['header'].items()}, 'lines': [{key.split(':', 1)[1]: value for key, value in line.items()} for line in item['lines']], 'issues': []}
        issues.extend(clean_output(mode, record, output))
    if not records:
        issues.append('No matching records. Adjust the row conditions before submitting.')
    shown = records[:limit]
    return {'passed': not issues, 'issues': list(dict.fromkeys(issues)), 'count': len(records), 'duplicateCount': duplicates,
            'rows': [{**item['header'], **(line or {})} for item in shown for line in (item['lines'] or [{}])][:100],
            'rawRows': [item['raw'] for item in shown],
            'headers': [{'id': item['id'], 'label': next(field['label'] for field in field_catalog(mode, record.target_entity) if field['id'] == item['id'])} for item in query['mappings'] if item['include']],
            'sourceHeaders': [{'id': ref, 'label': str(metadata['tables'][ref.split('.', 1)[0]])+'.'+ref.split('.', 1)[1]} for ref in (shown[0]['raw'] if shown else [])]}


def import_rows(mode, record, limit, offset):
    query, _, rows, issues, _ = read_rows(mode, record)
    if issues:
        raise ValidationError(issues)
    return [({**item['header'], **{key.removeprefix('base.'): item['raw'][key] for key in query['keys']}}, item['lines']) for item in rows[offset:offset+limit]]
