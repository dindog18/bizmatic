> The primary AP/AR Extraction Setup now uses **Record First**. See [SETUP.md](SETUP.md) for its frontend/backend structure, real document/query tests, and confirmed-save protocol. The conversational endpoints below remain compatible with existing integrations.

# AP and AR backend MVP

The accounting workspaces read and write Django records. They do not load demo
fixtures or browser storage. AP and AR keep separate models and reconciliation
rules. Their identical workspace operations share small services in
`accounts_receivable/services/`; each function receives `ap` or `ar` explicitly.

## Document workflow

1. Create the customer or supplier, or route an account document first.
2. In Extraction setup, create a document configuration for the target record.
   Write the instructions and account lookup rules, then review and submit it.
3. Route saved extracted text from Documents or Batches.
4. Each LLM-matched destination starts accounting extraction automatically using
   the one submitted module-wide document configuration for its target. Human
   review remains pending. If processing fails, use Retry extraction on the route
   or its routing log. If
   several configurations exist, choose one in the route's processing controls
   and click Process record. Manually added destinations process on approval.
5. Open the created accounting record or its LLM attempt from the route.

One route creates one header and its lines. Multiple destinations are processed
independently. Unknown accounts, missing required fields, ambiguous output,
invalid lines, or inconsistent totals fail without saving partial records. The
provider response remains in LLM activity. Fix the configuration/source and retry.
Completed routes are idempotent. A new route cannot silently re-create an already
processed document/target or overwrite an existing reference. Existing accounting
records stay read-only in the extraction registers.

AP/AR setup tests and final extraction saves check each order/invoice line against
quantity × unit price − discount + tax, rounded to cents using half-up rounding.
Setup uses a one-cent tolerance; reconciliation uses its configured price tolerance
(one cent by default). Header charges remain separate. Quantities must be positive.
Reconciliation checks saved source lines again and keeps inconsistent
records in exception without rewriting the source amounts. Discrepancies outside
the stored monetary range return a validation message instead of being saved.

Configurations are drafts until the user submits them. Editing a saved profile
returns it to draft; its previous submitted snapshot remains in history.
Assistant calls save proposals and logs, but applying suggestions to a draft and
submitting that draft are separate user actions. Only one target record per
source is supported in this MVP; split documents containing multiple invoices.

## Database workflow

Create and refresh a PostgreSQL connection in Database extraction. In accounting
Extraction setup, select its captured header/line tables, map fields, configure
account lookups, key columns and joins, and submit the profile. Import records
reads up to 100 headers per request using an explicit limit and offset. Each
header supports up to 1,000 lines. Queries use a read-only transaction, quoted
identifiers from metadata, and bound values. No user-entered SQL is executed.

Each valid record saves atomically; a failed row does not erase successful rows.
Imports save a `DatabaseImportRun` with the configuration snapshot and per-row
outcomes. Request IDs prevent duplicate request execution. Duplicate policy can
hold existing rows for review or skip them. Existing rows are never overwritten.
Database source keys are compared by connection/schema/table across snapshots.
Use a source account with SELECT permission on the configured business tables.

## Accounting actions

PO, delivery receipt, sales invoice, and payment detail pages offer Delete record
in both AP and AR. Confirming deletion removes the record and its line items;
source documents and extraction attempts are retained. Records linked to a
reconciliation case, a line match, or a payment allocation cannot be deleted
until those links are removed. Running extraction and stale confirmations are
also rejected. Deletion uses a CSRF-protected POST and an atomic transaction.

Account creation/editing, case membership, line matches and payment allocations
use CSRF-protected POSTs and server validation. Stale edits are rejected. Existing
matching and settlement rules remain in each app's `services/reconciliation.py`.
Amounts are stored and validated with Decimal. Dashboard/aging summaries select
one currency and use the current application date. Currency conversion is not
implemented. Only cleared payments settle invoices.

Both overview dashboards show Total PO amount and Open order amount using saved
order header totals. AP summarizes company POs; AR summarizes customer POs.
Total PO amount includes draft, open, and closed orders and excludes cancelled
orders. Open order amount includes only orders marked open and represents their
full order value, rather than an uninvoiced or undelivered remainder. Both cards
show order counts and respect the report currency, including currencies found
only on purchase orders.

## Files

- `models.py`, `migrations/`: plain models and schema changes.
- `services/reconciliation.py`: existing module-specific business rules.
- Shared `services/catalog.py`: explicit AP/AR model map and field allowlist.
- Shared `services/configuration.py`: draft validation, submission and snapshots.
- Shared `services/llm.py`, `assistant.py`: provider calls, logs and proposals.
- Shared `services/extraction.py`: account resolution and atomic header/line saves.
- Shared `services/imports.py`: bounded PostgreSQL imports and run history.
- Shared `services/records.py`: account, case, match and allocation writes.
- Shared `services/pages.py`, `http.py`: page data and JSON action handling.
- `router/services/handoff.py`: automatic route extraction, approval, and retry status.

## Setup and limits

Run `python manage.py migrate` and restart Django. The `ACCOUNTS_PAYABLE_*` and
`ACCOUNTS_RECEIVABLE_*` sections in `.env.example` configure each module independently,
including its provider, model, timeout, input limit, and output token limit.
These module settings apply to record extraction. Both configuration assistants use
the separate `CONFIG_ASSISTANT_*` provider, models and request limits, selected in
`services/llm.py` when `services/assistant.py` requests a proposal. Blank API keys
and base URLs reuse `DOC_EXTRACTION_*` through `document_extraction/services/llm.py`.
Credentials never enter request snapshots. Restart Django after environment changes.

This MVP runs provider calls and imports within the HTTP request. Configure the
server timeout accordingly. Interrupted workers can leave processing attempts;
an administrator must inspect their logs/created records before marking a stuck
route failed or retrying an import. There is no background queue or automatic
retry. The workspace follows the existing application's access model; all POSTs
require CSRF tokens. List pages load workspace records for client filtering, so
server pagination is a later scaling improvement.

Tests use a disposable database and mocked external providers/source reads.

## Configuration assistant logs

Each accepted assistant message creates an `LLMExtractionLog` in its AP or AR
module with purpose `configuration`. It preserves the provider, model, exact
request and conversation, configuration revision/snapshot, original response,
token counts, elapsed provider time, status and errors. Invalid proposals and
save failures are marked failed; completion means the proposal was validated
and saved, not that its changes were applied or its configuration submitted.
Input validation rejected before an LLM attempt does not create an attempt log.

Open **LLM activity** and filter Purpose to **Configuration assistance**, or use
the attempt link in the assistant conversation/error. `CONFIG_ASSISTANT_LOG_LEVEL`
controls terminal progress through `bizmatic_django/settings.py` and
`accounts_receivable/services/assistant.py`; terminal messages include attempt
IDs and metrics without prompt text, responses or credentials.

## Conversational extraction setup (AP and AR)

New setup pages require an explicit record type and extraction source before chat.
AR offers Customers; AP offers Suppliers; both offer Purchase orders, Delivery
receipts, Invoices and Payments, with Document extraction or Database setup.
Each combination has its own working draft and conversation for the lifetime of
the page. Switching back restores its answers; switching from a saved profile to
another combination starts a separate new configuration. Unsaved sessions are not
persisted across page reloads. The live **What I’ve understood** guide and the
selected requirements panel update as answers change. Describe formatting and business rules, ask questions,
or correct an answer. The assistant builds the working configuration; detailed
settings remain available for manual changes. Unsaved work stays in the current
page and leaving it prompts a warning. Assistant attempts are persisted as logs,
but chatting does not save a configuration or alter an existing submitted snapshot.

Both chat and sample previews use **only `CONFIG_ASSISTANT_*`**. They never fall
back to AP/AR extraction models. No additional environment variables are required.
Local Ollama responses use a [constrained JSON schema](https://docs.ollama.com/capabilities/structured-outputs)
and temperature zero; other providers receive the same schema in their system
instructions (including repair requests) and use JSON responses plus server validation.
Database mapping shorthand such as `"supplier_name": "supplier_company_name"`
is normalized to `{"source": "supplier_company_name", "transform": "identity"}`
before validation. This does not bypass destination-field or source-column checks.
Invalid mappings report the specific shape, transform, or selected-table column
requirement so repair requests can correct the problem without guessing.
Partial nested answers preserve earlier settings; an empty object explicitly clears
that setting. Context and response schemas contain only the selected record’s
fields and the applicable document/database settings. The backend rejects missing
or mismatched selections and assistant attempts to switch record/source. Required
fields are shared with extraction/import validation. Database chats include enabled
connection names, the latest completed schema snapshots (up to 100 tables per
source), and up to 100 active account identifiers. Credentials are excluded.
The assistant can request one bounded context operation per message: refresh a
selected connection's schema, or read one header and its bounded lines using saved
table metadata and current mappings in a read-only transaction. An invalid response gets one format repair attempt. Tool errors are
returned to the assistant as missing evidence; generated SQL is never executed.

**Try one document** accepts pasted text or an existing document extraction. It
shows `{ "record": {...}, "lines": [...], "issues": [...] }`, checks the destination
field names and values, and flags missing or ambiguous account matches. This is a
preview: it never creates accounting records. Refresh the preview after changing
instructions. External database reads and schema refreshes use existing connection
permissions and timeouts.

Every save starts with a backend review and an **Is everything correct?** dialog.
The user checks the confirmation box and chooses **Confirm & save**. Saving as a
draft is also confirmed. Only the active configuration action creates a submitted
snapshot. A signed, 30-minute review token binds the exact configuration, record,
revision, module, user and draft/activation choice; changed or stale submissions
are rejected. Existing API callers must adopt this confirmation protocol.

**Refresh context** reloads requirements and saved metadata while retaining answers.
**Refresh database schema** inspects the selected connection; select a table from
the new snapshot to use it. **Clear chat** removes only working conversation history
and supports **Undo clear**. **Reset context** asks for confirmation, then clears the
conversation and all configuration answers (including names, business context,
tables, mappings, instructions, custom rules and samples). Only the selected record
type and extraction source remain; standard formatting and required-field defaults
are restored. Other chats and accounting records are untouched. For saved profiles,
the reset persists immediately, increments the revision and returns the setup to
draft; a new review and confirmation are needed to activate it again. Previous
submitted snapshots and LLM logs remain audit evidence and are not included in the
next assistant prompt. Resetting an unsaved chat does not create a configuration.

Shared JSON actions under each module's `/api/` prefix:

- `configuration-reset-context[/ID]/`: `{selection, revision?, confirmed: true}` →
  cleared record and selection. Saved records require the current revision and
  matching selection; stale requests receive HTTP 409. No LLM call is made.
- `configuration-context[/ID]/`: `{selection, configuration?, inspect_schema?}` →
  selected catalog, required setup parameters, features and available metadata.
  `selection` is `{target_entity, source_type}` and must match the current draft.
- `configuration-chat[/ID]/`: `{selection, configuration, messages, message}` → unsaved record,
  updated source metadata and attempt ID.
- `configuration-preview[/ID]/`: `{configuration, text_log_id?}` → sample output,
  source text and attempt ID.
- `configuration-review[/ID]/`: `{configuration, submit}` → `confirmation_token`.
- `configuration[/ID]/` (draft) or `submit[/ID]/` (activate):
  `{configuration, messages, confirmation_token, confirmed: true, submit}`.

Validate using `python manage.py test accounts_receivable.test_configuration_chat
accounts_receivable.test_backend`. Tests use mocked providers and a disposable DB.
