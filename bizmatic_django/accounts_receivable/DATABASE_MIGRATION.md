# Database migration and data updates in AP/AR

Database extraction copies mapped external PostgreSQL values into Bizmatic's local
accounting models. All external queries run in read-only transactions. The source
database is never modified by migration or Update data.

## Configure and migrate

1. Choose the record type and Database source in Extraction setup.
2. Choose the source table, join its related tables, map fields, and refine rows.
   For JSON items, enable **Items are stored in a JSON column**, choose the column
   and collection path (for example `details`, `/DATA`), and map item fields using
   paths such as `/MODEL`, `/QUANTITY`, `/PRICE`, and `/TOTAL_PRICE`. Line numbers
   can be generated automatically.
3. Run **Test query** for a small preview. This does not save anything.
4. Choose **Review full migration**. Every matching source identity is streamed
   and checked for mapping, type, account, model, line, uniqueness and total errors.
   The review shows create/update/unchanged counts and keyed errors. Correct the
   source, field mappings or conversions, or ask the existing Setup assistant for
   mapping help. Assistant calls continue to use the existing LLM usage logs.
5. Only a successful full review offers **Migrate all & save**. Confirming repeats
   validation, checks that the reviewed source/local data still matches, migrates
   every matching record, and saves/activates the configuration in one transaction.
   Any failure rolls back all accounting and configuration changes.

Database setups cannot bypass the full migration through draft-save, the legacy
configuration-save endpoint, or the old import endpoint. Document setups keep their
existing draft/test/review/save workflow.

## Update an existing setup's data

The former **Import saved database records** panel is now **Update data**.
Choose **Review all data updates**, fix all reported errors, then confirm
**Update data**. This uses the saved active configuration and scans all matches.
New identities are created, existing source identities are updated, and unchanged
records are skipped. It does not delete local records missing from the source.

Supplier/customer records match by their configured account code. Transaction
records match by database connection, schema/table name and original source key,
including across metadata snapshots. Existing line IDs are retained by line number.
Updates change mapped fields while retaining other accounting fields. Changes to
records used in reconciliation, matched lines or payment allocation, and finalized
records, are blocked and reported for resolution. Changing setup mappings requires
a new Test query and full migration review before saving.

## Execution and API

Both modules use the same service, `services/database_updates.py`, and their
existing POST/JSON/CSRF API prefixes. No new Django model or schema migration is
required; successful operations are audited with the existing DatabaseImportRun.

| Action | Request |
| --- | --- |
| `setup-test[/<id>/]` | `configuration`, `limit` (5/10/25) |
| `setup-migration-review[/<id>/]` | `configuration`, `migration_test_token` |
| `setup-migration-apply[/<id>/]` | same configuration, `migration_token`, `confirmed: true`, optional `messages` |
| `setup-update-review/<id>/` | saved `revision` |
| `setup-update-apply/<id>/` | saved `revision`, `migration_token`, `confirmed: true` |

Full reviews return `passed`, `count`, `created`, `updated`, `unchanged`,
`error_count`, and `errors` containing source keys and messages. The first 200
error records are returned; `errors_truncated` explicitly indicates additional
errors. Every record is still validated. A signed 30-minute confirmation receipt
is issued only when the complete result has no errors. Reusing a successful
operation's receipt cannot create another migration run.

There is no whole-dataset row limit or browser batching. A server-side source cursor
keeps complete identities together. Individual records remain bounded to 5,000
joined source rows, 8 MiB source data and 1,000 items. Per-query connection/statement
timeouts still apply. Reviews and commits are synchronous HTTP requests; large
datasets need sufficient web-server request timeouts. Keep the page open until
completion. A source/database timeout or validation failure during commit rolls back the transaction.
If the client loses the response after commit, reload and review again; source
identity matching and unchanged-record detection prevent duplicate records.

No automatic LLM conversion or automatic source correction occurs. Invalid values
are surfaced for review; explicit mapped conversions are applied consistently in
preview, review and commit. No automated tests were added or run for this change,
as requested; manual exercise of the AP and AR flows is required.

## Delete configurations

Both AP and AR expose **Delete** on the configuration list and **Delete configuration**
inside saved setups, for document and database configurations. The confirmation
checks the current revision; active operations must finish before deletion.
Deletion removes the configuration while retaining accounting records, case links,
import/migration/update runs and LLM activity with their original snapshots.
Apply the AP `0012` and AR `0011` history-preservation migrations before using
this action. The shared API action is `configuration-delete/<id>/`, with
`revision` and `confirmed: true`; CSRF protection remains required.

## Optional line items

All line-item source fields are optional in document and database setup for AP
and AR. Records can be validated, migrated, saved and extracted with no item rows.
Blank placeholder rows are ignored; real rows receive generated line numbers when
needed. Supplied values still undergo type and model validation. Header totals
are checked when supplied; line arithmetic and aggregate totals are checked only
when the necessary item values are present. Matching workflows keep their existing
requirements for sufficient quantities and amounts. Header-only database updates
retain any previously saved item rows. No new schema migration is needed.
