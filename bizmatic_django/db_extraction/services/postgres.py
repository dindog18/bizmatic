"""Read PostgreSQL system catalogs in a bounded, read-only transaction."""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ..models import DatabaseSource


EXTRACTOR_VERSION = "0.1.0"


class InspectionError(Exception):
    """Safe user-facing error with no server diagnostics or credentials."""


@dataclass
class CatalogSnapshot:
    database_name: str
    server_version: str
    schemas: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    constraints: list[dict[str, Any]]
    indexes: list[dict[str, Any]]


def connection_parameters(source: DatabaseSource) -> dict[str, Any]:
    """Build keyword parameters; never log the result or build a display DSN."""
    # Client option names are prescribed by PostgreSQL.
    # noinspection SpellCheckingInspection
    parameters = {
        "host": source.host, "port": source.port, "dbname": source.database_name,
        "user": source.username, "password": source.password,
        "sslmode": source.ssl_mode, "connect_timeout": min(source.connect_timeout, 60),
        "application_name": "database_metadata",
        "options": "-c default_transaction_read_only=on -c statement_timeout=30000 -c lock_timeout=5000",
    }
    if source.ssl_root_cert:
        # noinspection SpellCheckingInspection
        parameters["sslrootcert"] = source.ssl_root_cert
    return parameters


def _schemas(connection, included_schemas):
    if connection.info.server_version < 140000:
        raise InspectionError("PostgreSQL 14 or newer is required for metadata extraction.")
    rows = connection.execute("""
        SELECT n.oid, n.nspname AS name, pg_get_userbyid(n.nspowner) AS owner,
               COALESCE(obj_description(n.oid, 'pg_namespace'), '') AS comment
        FROM pg_catalog.pg_namespace n
        WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
          AND n.nspname <> 'information_schema'
          AND has_schema_privilege(n.oid, 'USAGE')
        ORDER BY n.nspname
    """).fetchall()
    if included_schemas:
        available = {row["name"] for row in rows}
        if set(included_schemas) - available:
            raise InspectionError("One or more selected schemas do not exist or are not accessible to this account.")
        rows = [row for row in rows if row["name"] in included_schemas]
    return rows


def test_connection(source: DatabaseSource) -> dict[str, Any]:
    """Test unsaved settings without changing either database."""
    try:
        with psycopg.connect(**connection_parameters(source), row_factory=dict_row) as connection:
            identity = connection.execute(
                "SELECT current_database() AS database_name, current_setting('server_version') AS server_version"
            ).fetchone()
            assert identity is not None
            schemas = _schemas(connection, source.included_schemas)
            return {**identity, "schema_count": len(schemas)}
    except psycopg.Error:
        raise InspectionError("Connection failed. Check the host, port, database, credentials, SSL settings, and network access.") from None


def inspect_database(source: DatabaseSource) -> CatalogSnapshot:
    """Collect definitions only. Never SELECT from a user table or view."""
    try:
        with psycopg.connect(**connection_parameters(source), row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            identity = connection.execute(
                "SELECT current_database() AS database_name, current_setting('server_version') AS server_version"
            ).fetchone()
            assert identity is not None
            schemas = _schemas(connection, source.included_schemas)
            schema_ids = [row["oid"] for row in schemas]
            tables = connection.execute("""
                SELECT c.oid, c.relnamespace AS schema_oid, c.relname AS name, c.relkind AS relation_kind,
                       pg_get_userbyid(c.relowner) AS owner,
                       COALESCE(obj_description(c.oid, 'pg_class'), '') AS comment,
                       CASE WHEN c.relkind IN ('v', 'm') THEN pg_get_viewdef(c.oid, true) ELSE '' END AS view_definition,
                       CASE WHEN c.relispartition THEN pg_get_expr(c.relpartbound, c.oid)
                            WHEN c.relkind = 'p' THEN pg_get_partkeydef(c.oid) ELSE '' END AS partition_definition,
                       c.relrowsecurity AS row_security_enabled
                FROM pg_catalog.pg_class c
                WHERE c.relnamespace = ANY(%s::oid[]) AND c.relkind IN ('r', 'p', 'f', 'v', 'm')
                ORDER BY c.relnamespace, c.relname
            """, (schema_ids,)).fetchall()
            table_ids = [row["oid"] for row in tables]
            columns = connection.execute("""
                SELECT a.attrelid AS table_oid, a.attnum AS ordinal_position, a.attname AS name,
                       format_type(a.atttypid, a.atttypmod) AS formatted_type,
                       tn.nspname AS type_schema, t.typname AS type_name,
                       CASE WHEN t.typtype = 'd' THEN tn.nspname ELSE '' END AS domain_schema,
                       CASE WHEN t.typtype = 'd' THEN t.typname ELSE '' END AS domain_name,
                       NOT (a.attnotnull OR t.typnotnull) AS nullable,
                       CASE WHEN a.attgenerated = '' THEN COALESCE(pg_get_expr(d.adbin, d.adrelid), t.typdefault, '') ELSE '' END AS default_expression,
                       CASE WHEN a.attgenerated <> '' THEN pg_get_expr(d.adbin, d.adrelid) ELSE '' END AS generated_expression,
                       CASE a.attidentity WHEN 'a' THEN 'ALWAYS' WHEN 'd' THEN 'BY DEFAULT' ELSE '' END AS identity_generation,
                       COALESCE(cn.nspname, '') AS collation_schema, COALESCE(coll.collname, '') AS collation_name,
                       COALESCE(col_description(a.attrelid, a.attnum), '') AS comment,
                       ic.character_maximum_length, ic.numeric_precision, ic.numeric_scale
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
                JOIN pg_catalog.pg_namespace tn ON tn.oid = t.typnamespace
                LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = a.attcollation
                LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid = coll.collnamespace
                LEFT JOIN information_schema.columns ic ON ic.table_schema = n.nspname AND ic.table_name = c.relname AND ic.column_name = a.attname
                WHERE a.attrelid = ANY(%s::oid[]) AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attrelid, a.attnum
            """, (table_ids,)).fetchall()
            constraints = connection.execute("""
                SELECT con.oid, con.conrelid AS table_oid, con.conname AS name, con.contype AS constraint_type,
                       pg_get_constraintdef(con.oid, true) AS definition,
                       con.conkey AS column_positions, con.confkey AS referenced_positions,
                       COALESCE(rn.nspname, '') AS referenced_schema, COALESCE(rc.relname, '') AS referenced_table,
                       con.confupdtype AS update_code, con.confdeltype AS delete_code, con.confmatchtype AS match_code,
                       con.condeferrable AS is_deferrable, con.condeferred AS initially_deferred, con.convalidated AS is_validated,
                       ARRAY(SELECT ra.attname FROM unnest(con.confkey) WITH ORDINALITY AS k(column_number, pos)
                             JOIN pg_catalog.pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = k.column_number
                             ORDER BY k.pos) AS referenced_columns
                FROM pg_catalog.pg_constraint con
                LEFT JOIN pg_catalog.pg_class rc ON rc.oid = con.confrelid
                LEFT JOIN pg_catalog.pg_namespace rn ON rn.oid = rc.relnamespace
                WHERE con.conrelid = ANY(%s::oid[]) AND con.contype IN ('p', 'f', 'u', 'c', 'x', 'n')
                ORDER BY con.conrelid, con.conname
            """, (table_ids,)).fetchall()
            indexes = connection.execute("""
                SELECT i.indrelid AS table_oid, c.relname AS name, pg_get_indexdef(c.oid) AS definition,
                       am.amname AS access_method, i.indisunique AS is_unique, i.indisprimary AS is_primary,
                       i.indisvalid AS is_valid, COALESCE(pg_get_expr(i.indpred, i.indrelid), '') AS predicate,
                       COALESCE(obj_description(c.oid, 'pg_class'), '') AS comment
                FROM pg_catalog.pg_index i
                JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid
                JOIN pg_catalog.pg_am am ON am.oid = c.relam
                WHERE i.indrelid = ANY(%s::oid[])
                ORDER BY i.indrelid, c.relname
            """, (table_ids,)).fetchall()
            return CatalogSnapshot(**identity, schemas=schemas, tables=tables, columns=columns, constraints=constraints, indexes=indexes)
    except psycopg.Error:
        raise InspectionError("Metadata extraction failed. Check connectivity, schema access, and whether the database is busy, then retry.") from None
