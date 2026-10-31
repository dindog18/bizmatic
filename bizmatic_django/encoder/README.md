# Encoder (local MCP MVP)

Encoder prepares external business operations from **existing routed extraction
text**. It does not upload files, run OCR, or change AP/AR extraction. Pages use
the shared Falcon layout, navigation, Django forms, CSRF controls, and original
file preview. All provider calls and writes use POST; GET/HEAD are read-only.

## Setup

From the repository root, using the project's Python environment:

```sh
python -m pip install -r requirements.txt
python bizmatic_django/manage.py migrate
python bizmatic_django/manage.py runserver 127.0.0.1:8000
```

Set these in `bizmatic_django/.env`, then restart Django:

```dotenv
ENCODER_LOCAL_ENABLED=true
```

In **Encoder → MCP connections → Add connection**, enter the server executable,
JSON argument list (for example `["/absolute/path/to/erp_mcp.py"]`), optional working
directory and environment variables as a secret JSON object such as
`{"ERP_API_KEY":"value"}`. Use the target server's documented configuration.
Prefer absolute paths. No shell expansion is performed.

**Test connection** initializes the MCP server and discovers tools without saving
anything or invoking a business operation. **Test and save connection** repeats
that test against the submitted values and saves only on success. Tool permissions
remain a separate explicit choice. Editing launch details or credentials resets
permissions; unchanged tool definitions can retain approval on an unchanged connection.

Secret environment values reuse Database Connections' encrypted field and external
credential key. Provision it once with `python bizmatic_django/manage.py init_db_credential_key`.
Blank secret input preserves existing values only for unchanged launch details;
otherwise re-enter them or explicitly clear them. Saved values are never rendered
back into the form. Do not put credentials in command arguments, which are ordinary
configuration. The server receives the SDK's small standard environment plus these
explicit variables. Legacy `ENCODER_STDIO_SERVERS` profiles remain readable for
existing connections; editing them replaces the profile with frontend-managed details.

No new login, OAuth, roles, or Bizmatic token is required. Encoder is disabled by
default. When enabled, middleware checks both the actual peer and Host for
loopback, independent of forwarded headers. Bind Django to `127.0.0.1`; do not
publish or reverse proxy these unauthenticated pages. Local process/connection
configuration is trusted operator configuration, not an isolation sandbox for
untrusted MCP server programs. Existing ERP authentication remains in force.

Mapping/chat use the existing `CONFIG_ASSISTANT_*` model, credentials, input,
output and timeout settings and `document_extraction.services.llm` transport.
Configure those just as for AP/AR configuration chat. No paid API is used in tests.

## Use

1. Open **Encoder → MCP connections**, add a connection by entering its local server details, and **Test and save connection**. Inspect schemas and explicitly
   permit intended encoding operations. Discovery never grants permission or
   invokes a business tool; removed/changed tool definitions lose approval.
2. In the existing Router, add a destination with module **Encoder**, target
   **Encoder job**. In its routing rule, choose the **MCP connection** and
   **Permitted operation**, alongside the normal human routing instructions.
   Only enabled connections and explicitly permitted discovered tools appear.
3. Upload/extract/review through Document Extraction and run normal routing.
   A successful handoff creates exactly one draft per route and automatically
   selects the rule's operation, builds reusable mappings and validates the payload.
   When fields are missing, shared AI prepares an initial local draft and starts
   the job's troubleshooting conversation. Unknown values stay missing and flagged.
   A failed handoff
   uses the existing Router retry path. Approve the source document and current
   route before execution. Encoder drafts can still be rejected/reopened in Router;
   processing/completed external jobs remain locked against route changes.
4. Open the prepared draft from Router or Encoder's queue. Review its routed
   operation and continue troubleshooting to supply missing values. Choose source
   paths/defaults/transforms or ask the contextual assistant for a correction.
   Required and optional fields are
   labelled; enums and booleans use selections; nested objects/arrays use JSON.
5. Save values or apply an AI proposal, then inspect validation issues and the exact
   prepared JSON. Applying a suggestion only edits the local payload and validates;
   it never calls MCP. Changes invalidate old execution confirmations and proposals.
6. Check the explicit confirmation box and **Confirm & execute**. The backend checks
   current route/source approval and revisions, enabled/permitted operation, signed
   payload identity, and live input schema before calling the selected tool.
7. Inspect the persistent execution history: source link, submitted payload, schema,
   connection snapshot, request ID, confirmation/finish times, result and errors.
   Use chat beside issues to propose corrections, inspect them, then apply or reject.

## Mapping

Reusable mappings are unique per connection/tool. Workspace source selectors show
existing JSON paths; a Markdown extraction exposes `text` for contextual AI mapping.
No second OCR or new document extraction log is created. Original routed text and
extraction foreign keys remain on Router's immutable input snapshot; Encoder stores
the separately prepared payload, and every execution stores its own submitted copy.

```json
{
  "product_code": {"source": "items.0.code", "transform": "upper"},
  "quantity": {"source": "items.0.quantity", "transform": "integer"},
  "warehouse_id": {"default": 2}
}
```

Transforms: identity, strip, upper, lower, integer, number, date_dmy, date_mdy.
No eval, Python, SQL or executable expressions. Source paths can supply whole nested
objects/arrays. Advanced JSON supports schema-permitted custom fields and complete
nested payloads. JSON Schema validation checks required fields, types, bounds,
enums, local references, nested arrays and formats; remote schema references are
rejected. Missing values are omitted/flagged; neither schema defaults nor AI can
silently invent a required business value.

Chat persists multi-turn job-specific messages, exact requests/responses and strict
payload/mapping proposals. Document/schema/tool output is explicitly untrusted
context, never tool authority. The assistant has no MCP callbacks or execution
function. A proposal is bound to its original job revision; stale proposals cannot
apply. AI accuracy still requires human review.

Routing snapshots retain the connection, operation and matching rule so later rule
edits cannot change an existing job. Multiple rules can select different operations
for the Encoder destination; the router must identify the matching rule. Ambiguous
responses stop for review. Initial AI preparation is labelled **Prepared automatically**;
later chat corrections still require Apply. No preparation path invokes an MCP business
tool. Handoff/request replay never regenerates an existing draft or repeats its AI call.
Provider failures leave a reviewable draft and a failed LLM activity entry.

Existing rules/drafts without an operation keep the manual selector. Edit and save
an existing Encoder rule to enable automatic preparation for future routing attempts.
Changes do not retroactively process old jobs. If the selected connection or permission
is unavailable, fix the rule/connection and rerun routing; existing jobs retain their
original configuration. Concurrent user edits invalidate an in-flight AI preparation.

## Retries and interruption

Requests use signed, expiring payload confirmations and unique request IDs;
reposting the same confirmation returns its prior attempt without another call.
A job cannot execute concurrently or execute again after completion. Each explicit
retry creates a separate attempt. There are no automatic mutation retries.

Timeouts, lost connections during a call, and tool-reported errors are recorded as
**unknown outcome**, since the ERP may already have changed. A retry requires either:

- an identical connection/tool/payload with a **documented** idempotency string
  parameter configured in Reusable mapping (Encoder supplies the stable job UUID); or
- explicit confirmation that the user checked the ERP and the prior call did not
  succeed. The reconciliation timestamp is retained on prior unknown attempts.

Never configure an arbitrary string field as an idempotency key. Actual deduplication
is the target server's responsibility. Changed payloads after unknown outcomes also
require reconciliation; the stable key is retained and the target may reject reuse.

If Django crashes while an attempt is processing, first stop/verify the original
worker is gone, then recover its claim without invoking the external system:

```sh
python bizmatic_django/manage.py recover_encoder_execution 123 --confirm-process-stopped
```

This marks it unknown/failed for review and reconciliation; it does not retry.

## Tests and synthetic local demo

```sh
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: python bizmatic_django/manage.py test encoder router document_extraction db_extraction accounts_receivable accounts_payable --noinput
python bizmatic_django/manage.py check
python bizmatic_django/manage.py makemigrations --check --dry-run
```

`encoder/mock_server.py` is an isolated SDK stdio server with synthetic receipt,
error and timeout operations, no ERP access or persistent external writes. For a
local walkthrough enter that script in Arguments and the project's Python
executable in Server executable, leaving environment variables empty. The example request key illustrates the input
shape; the fixture does not promise ERP deduplication.

## MVP limits

STDIO and Streamable HTTP; each operation opens a bounded session, with no connection pool,
workers, scheduling, OAuth, automatic retries or general agent orchestration.
Transport uses the [official Python MCP SDK stdio client](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/examples/snippets/clients/stdio_client.py).
Connection launch details are maintained in the local UI and tested before saving.
Top-level mapping rules can carry nested values; complex conditional schema branches
and deeply nested per-item mappings use the JSON editor/assistant. No ERP master-data
lookup or automatic product/customer matching is performed. Unknown identities are
review issues. Catalogs are capped at 100 pages, mapping rules at 200 fields, and
validation reports at 100 issues. Connection and tool responses are retained locally
and may contain business data. Keep this development database private.


## Streamable HTTP connections

Like [Codex Add MCP](https://learn.chatgpt.com/docs/extend/mcp), select a transport:
STDIO uses Command, Arguments, Working directory and Environment variables.
Streamable HTTP uses Server URL, optional Bearer token environment variable,
HTTP headers (secret JSON), and HTTP headers from environment variables (JSON
mapping header names to variable names). Only the selected transport's fields
are used. A URL is required for HTTP; a command is required for STDIO.

Bearer/environment-header variable names refer to the Django process environment;
missing variables are reported before connecting. Literal header values are
stored encrypted with the existing credential key, never rendered back into the
form, and must be re-entered or explicitly cleared when the HTTP destination or
authentication configuration changes. Use HTTPS for remote credentials; local
HTTP endpoints are also supported. URL userinfo and fragments are rejected.
No OAuth flow is implemented. Existing MCP server authentication remains required.

Testing and execution share the same SDK client, bounded initialize/discovery,
schema checks and approval controls for both transports. Changing transport,
endpoint, or headers invalidates execution confirmations and tool approvals.


The connection UI uses add/remove rows matching Codex Add MCP, with no JSON typing
required: one argument per row, key/value environment variables or HTTP headers,
header/environment-name pairs, and environment-variable passthrough names. Values
are passed literally (arguments are never shell-split). Passthrough reads the Django
server environment and reports missing variables; explicit environment rows take
precedence over a passthrough value of the same name. All populated keys must be
unique. On edit, secret values are never populated into the rows; enter a complete
replacement set or leave rows empty to retain unchanged secrets. Use the explicit
Clear checkbox to remove saved secrets.

## Setup and page help

Activate Encoder in Settings & setup to include its checklist in reminders.
Checks cover local access, a tested MCP connection, permitted operations, shared
assistant configuration and an Encoder routing destination/rule. Secret key
storage is optional until you need encrypted credentials. Checks use local
metadata only and never invoke a provider or MCP server, or decrypt stored secrets.
The Help button has dedicated tours for the queue, job workspace, connection
list/form/tool permissions, reusable mappings and execution history. Module
activation here is a workspace-wide reminder preference, not an execution or
permission bypass. Encoder has its own Encoding & integrations sidebar group.

## Contextual chat and LLM activity

The chat workspace separates the current payload into readable nested field/value
rows and **Needs your input** cards derived from the MCP JSON Schema. Missing
fields show their parameter path, expected type and available description/choices.
**Provide details** fills a field-specific prompt without sending it. AI proposals
have the same structured review; explanations and raw JSON remain available in
expandable sections. Current accepted/prepared proposal warnings remain prominent,
including reported omissions and uncertainty. These are prepared values, not
independently verified extraction matches. Reviews show at most 100 value rows.
Assistant Markdown supports formatting with raw HTML, images and links disabled.

The job chat shows separate user/assistant messages, timestamps, provider/model,
reported input/output tokens and a link to each attempt. Prompt shortcuts and
Retry fill the composer for review; they never send or execute automatically.
Corrections must still be inspected and applied explicitly, then validated.

Encoder → LLM activity lists assistant attempts with status, token counts and
elapsed milliseconds. Open an attempt to inspect its exact request/response and
sanitized error. Requests use the existing CONFIG_ASSISTANT provider adapter and
shared token-usage parser. Truncated or invalid suggestions and provider failures
are logged as failed; reported usage is retained even when parsing fails. Missing
usage stays unknown, rather than zero. Historical messages without metadata remain
Not recorded. Terminal INFO logs include IDs, provider/model, status, tokens and
duration, with no prompts or credentials (ENCODER_LOG_LEVEL controls verbosity).
These local logs contain source business context; protect the development database.

## Reset a workspace

Use **Reset workspace**, expand the reset control, acknowledge that ERP changes
are not undone, and confirm. Reset starts a new numbered cycle with an empty
payload, mappings and conversation; it retains the document, MCP operation,
reusable profiles and stable idempotency key. It makes no AI or MCP calls.
A reset snapshot retains the previous draft, validation issues, schema and error.
**Previous conversations** shows archived messages; **Saved drafts before reset**
shows snapshots. Execution history and LLM activity retain all cycles.
Archived suggestions cannot be applied; old execution confirmations become stale.
Running chat/execution requests block reset. Unknown external outcomes continue
to require reconciliation across cycles. Successful external writes remain real;
review the ERP before explicitly executing a new cycle to avoid duplicates.

Remote Streamable HTTP endpoints must use HTTPS. Plain HTTP is accepted only for
localhost or literal loopback addresses, and rejected before loading credentials.
