# Database query builder (AP and AR)

Database Extraction Setup now prepares source data before matching accounting
fields. Document extraction uses its existing annotation flow.

## Research and scope

The design follows Microsoft's documented Power Query editor patterns:

- [Applied Steps](https://learn.microsoft.com/en-us/power-query/applied-steps):
  ordered, named transformations; edit, remove, reorder, and preview a prefix.
- [Data types](https://learn.microsoft.com/en-us/power-query/data-types):
  column types and deliberate conversions before loading data.
- [Structured column expansion](https://learn.microsoft.com/en-us/powerquery-m/table-expandtablecolumn):
  expand record fields into columns and item arrays into rows.
- [Merge queries](https://learn.microsoft.com/en-us/power-query/merge-queries-overview):
  match related tables and expand their business columns.
- [Query folding](https://learn.microsoft.com/en-us/power-query/query-folding-basics):
  execute supported shaping operations at the data source.

This is a focused PostgreSQL preparation builder, not an implementation of the M
language. It supports selecting/renaming columns, left/inner merges with multiple
matching keys, JSON object/array expansion, text/integer/decimal/date/datetime/
boolean/JSON conversion, locale separators for decimals and common source date
formats, nested AND/OR filters, multiple sort columns, trim, uppercase, text
replacement, and duplicate removal within each original source record.
Append/union, grouping/aggregation, custom formulas, and arbitrary SQL are outside
the current scope.

## Using the editor

1. Select Database in an AP or AR extraction setup. Choose the connection and main
   table in Source tables. Refresh preview to view the first 50 source rows.
2. Select a column heading, then a toolbar transformation. New steps are appended
   to Applied Steps. Refresh preview, or select an existing step to preview its
   result. Previous/Next retrieve pages at PostgreSQL, not from a full local copy.
3. For `VANS_purchaseorder.details`, use Expand JSON, item rows, path `/DATA`.
   After previewing the input to the step, Discover fields can suggest keys.
   Typical paths are `/MODEL`, `/QUANTITY`, `/PRICE`, and `/TOTAL_PRICE`.
   Missing fields become null, empty arrays retain the header, and repeated
   items retain their array positions. Expanded fields start as text; use Change
   type for quantities and amounts.
4. Merge the appropriate supplier/customer table using its PK/FK relationship.
   Declared schema relationships suggest matching pairs. Choose the account code
   column, or change Scope & formatting to match an existing account by name.
   A left join keeps main rows with missing account matches visible for review.
5. Continue to Match accounting fields. Match prepared columns to header/line
   fields, or supply constants. Line fields, including Line no, are optional.
   Repeated identical headers from a merge/expansion form one source record even
   when no line fields are matched; conflicting header values still need review.
   Suggest field matches uses unambiguous column names and makes no LLM request.
6. Validate mapped records checks five complete accounting records. Review full
   migration then checks every matching record. Migrate all & save is available
   only after a successful full review and explicit confirmation. Saved setups
   can use Update data with the existing review and transaction safeguards.

Changing a main source asks before discarding unsaved transformations. Removing
or reordering a step can invalidate later references; these are reported rather
than silently changed. Browsing and previews never save accounting records.

## Backend and compatibility

- No new models or Django migrations are needed. Recipes live in the existing
  `ExtractionConfiguration.setup_data.database.pipeline` JSON field.
- Recipe version 1 stores `sourceKeys` and ordered `steps`; final destination
  mappings remain in `database.mappings`.
- `services/setup/pipeline.py` validates recipes, compiles PostgreSQL CTEs using
  schema identifiers, and binds all filter/replacement/JSON pointer values.
- The existing `setup-preview` JSON action returns `columns`, `rows`, `offset`,
  `limit`, `has_more`, and the selected prefix `step` for both accounting modules.
- The existing query compiler dispatches recipes to the new compiler. The same
  grouped record stream feeds validation, full migration, and Update data.
  Accounting reads transfer only mapped columns and source/item IDs, so large
  original JSON documents are not retransmitted for every expanded item.
- Original source keys are retained as hidden, immutable columns. Merge PKs and
  JSON ordinality preserve item identity. Rename/remove/type steps do not change
  source provenance. Duplicate removal never collapses separate source records.
- Connections, encrypted credentials, saved schema snapshots, 30-second statement
  timeout, read-only repeatable-read transactions, accounting validation, signed
  review receipts, configuration revision history and deletion are reused.
- Old configurations remain readable by the old backend. Opening one in the new
  editor converts its joins, JSON mappings, filters and sorts in memory and marks
  it unsaved. Its stored definition changes only after migration confirmation.
- The editor bounds recipes to 50 steps and prepared tables to 250 columns;
  previews use 25/50/100 source rows with a 4 MiB response guard. Full migration
  still streams all matching source identities and uses existing per-record bounds.
- Invalid conversions stop preview/migration. No invalid values are silently
  replaced with null. No LLM, source write, or automatic migration is involved.

No additional packages, environment settings, services or scheduled jobs are
required. PostgreSQL must support CTEs and JSONB lateral expansion (the existing
PostgreSQL connection is reused).
