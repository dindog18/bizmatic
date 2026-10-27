# Record First extraction setup

The primary configuration screens are `/accounts-payable/configuration/new/` and `/accounts-receivable/configuration/new/`. Existing `/configuration/<id>/` routes edit saved profiles with the same interface. `target` and `source` query parameters select the initial record and source for a new profile. Old `/configuration-lab/record-preview/` bookmarks redirect here; the other design alternatives were removed.

AP and AR keep separate configuration models, records, logs and revisions. They share the UI and services with an explicit `mode` argument, following the project's `views.py` → `services/` → models pattern. No new dependencies are required.

## Where the code lives

| File | Responsibility |
| --- | --- |
| `ui.py`, `templates/accounting/setup.html` | Route context, model field catalog and Falcon page shell. |
| `static/accounting/setup/workspace.js` | Record/source selection, configuration fields, API calls, review/save and bounded imports. |
| `static/accounting/setup/documents.js` | Editable extracted text, annotation colors, prompt editing, expected values and test results. |
| `static/accounting/setup/database.js` | Table/column pickers, table connections, nested row filters, sorting and test preview. |
| `static/accounting/setup/annotations.js` | Native text-selection offsets and inferred Markdown labels. No model simulation. |
| `static/accounting/setup/query-state.js` | Available columns, declared foreign-key paths and unused-connection cleanup. No SQL or simulated rows. |
| `services/setup/context.py` | Actual destination fields, completed schema snapshots, composite foreign keys and successful text/OCR extractions. |
| `services/setup/documents.py` | Validate annotations, generate a prompt and test it using `CONFIG_ASSISTANT_*`. |
| `services/setup/database.py` | Validate and compile the structured query; read, group and validate actual source rows. |
| `services/setup/configuration.py` | Bridge Record First state into existing extraction profiles; share runtime type/account/totals checks. |
| `services/setup/actions.py` | API orchestration, assistant chat, signed passing-test receipts and confirmed saves. |

`services/http.py` dispatches the `setup-*` actions. `services/configuration.py` persists the versioned `setup_data` JSON alongside the existing fields and submitted snapshot. Separate AR/AP migrations add that field. Existing configurations and runtime providers remain supported.

## Document flow

Choose a successful extracted document or paste text/Markdown. The picker uses routing's existing preference: a human-marked accurate result first, then the newest successful text or OCR result. Editing the working text does not edit its source extraction. Applying changed text clears obsolete annotation offsets and tests.

Highlight values and assign them to exact header or line field IDs (`header:supplier_name`, `line:quantity_invoiced`, etc.). Field colors are consistent across the text and field panel. Required fields are labeled separately. Rules can extract annotated evidence, use an approved constant, describe an extraction instruction, or explicitly leave an optional value empty. Line numbering defaults to a rule that numbers items from 1; other line rules apply to every returned item row. Browser offsets are UTF-16 and are validated accordingly on the server.

Prompt generation, questions and document tests use only `CONFIG_ASSISTANT_*` from `.env`, through the existing logged provider transport. The backend supplies the actual model catalog and annotations, not fake records. Test requests omit expected answers and annotation example values. Results are validated against destination fields, types, required values, account lookup policy, unique line numbers and the same header/line totals checks used during record creation. Expected values verify the mapped header and example line; every returned line is validated and shown in the full JSON result. Testing another document requires expected values for its mapped fields.

Existing `ACCOUNTS_PAYABLE_*` / `ACCOUNTS_RECEIVABLE_*` settings still control actual routed record extraction; they do not generate or test setup prompts.

## Database flow

Choose an enabled connection with a completed schema snapshot. Map each field using its own Table → Column selectors. The starting record table is inferred from those choices and existing field matches; no global starting-table question is shown. Declared FK paths can add intermediate tables and preserve every pair in a composite relationship. Technical auth/audit relationships are not used to guess business relationships. Unknown relationships require explicit column matches.

Conditions and sort entries also choose their table and column independently. Nested AND/OR groups, multiple join pairs, constants, optional fields, exact duplicate removal, type conversion and composite identifiers are supported. Primary keys are used automatically; custom Table → Column identifiers are under Advanced row identification. Schema refresh maps existing table names to new snapshot IDs and clears unavailable columns for review.

The backend checks every identifier against the selected connection/snapshot and quotes it with Psycopg `Identifier`. Condition values are bound parameters. There is no user/LLM SQL execution. Queries run with the source's connection/statement timeouts in a read-only repeatable-read transaction. A 5,000 joined-row bound protects preview/import requests; exceeding it requires narrower conditions. It is a resource bound, not a fixed UI limit on connections or conditions.

Tests show 5, 10 or 25 mapped records and selected source columns/identifiers. Repeated header keys, ambiguous header values, missing line matches and invalid values block activation. Line rows are grouped by header keys and deduplicated by their actual source primary keys, preserving identical item values with different line IDs. The activated profile uses the same query plan in `services/imports.py`; request IDs retain the existing idempotent import behavior.

## Save protocol

- `setup-context`: catalog, source schema and extracted-document choices; `inspect_source` explicitly refreshes a schema.
- `setup-preview`: preview a prefix of the ordered database transformation recipe with source-side pagination, independently of accounting field matches; see [QUERY_BUILDER.md](QUERY_BUILDER.md).
- `setup-document`: read a chosen `text:ID` or `llm:ID` extraction without changing it.
- `setup-chat`: unsaved guide changes and conversation through the setup provider.
- `setup-generate`: create the document prompt from the current annotations.
- `setup-test`: execute the current document/query test and return a signed `test_token` only on success.
- `setup-review`: validate the exact current configuration and issue a `confirmation_token`. Activation requires a current passing test; a draft does not.
- `setup-save`: document setup requires explicit confirmation and the matching review token; database setups use the full migration endpoints described in [DATABASE_MIGRATION.md](DATABASE_MIGRATION.md).

Test receipts bind the module, configuration ID/revision, user, source-connection revision and exact normalized configuration. They expire after 30 minutes. Changed fields, source choices or stale revisions require another test/review. Saving increments the revision and preserves the submitted snapshot. Document setup does not create accounting records while saving. Database setup now requires a full migration review and commits the configuration and all mapped accounting records together. Saved database setups use Update data for subsequent full reviews and atomic updates. See [Database migration and updates](DATABASE_MIGRATION.md).

## Verification

From the repository root:

```sh
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: .venv/bin/python bizmatic_django/manage.py test accounts_receivable.test_record_setup accounts_receivable.test_backend accounts_receivable.test_configuration_chat accounts_receivable.test_frontend db_extraction document_extraction --noinput
node --test bizmatic_django/accounts_receivable/frontend_tests/setup-state.test.cjs
.venv/bin/python bizmatic_django/manage.py check
.venv/bin/python bizmatic_django/manage.py makemigrations --check --dry-run
```

Python tests use a disposable application database and mocked provider/source reads. Live tests use saved connection permissions and the configured external provider; provider calls create LLM attempt logs. Preview tests never create accounting records.
