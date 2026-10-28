# Data flow and trust boundaries

## Current implementation

```mermaid
flowchart TD
    Browser["Browser: no application login gate"] --> Docs["Document views and services"]
    Browser --> DB["Database views and services"]
    Docs --> Files["Local originals"]
    Docs --> Text["PDF text and Office parsers"]
    Docs --> OCR["Image provider calls"]
    Text --> App["Bizmatic database: logs and review flags"]
    OCR --> App
    DB --> Catalog["ERP catalog SELECTs: read-only transaction"]
    Catalog --> Snapshots["Bizmatic database: schema snapshots"]
```

Source: [bizmatic_django/document_extraction/views.py:24](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/document_extraction/views.py#L24), [bizmatic_django/document_extraction/util.py:22](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/document_extraction/util.py#L22), [bizmatic_django/db_extraction/services/postgres.py:81](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/db_extraction/services/postgres.py#L81). There is currently **no path from source transaction rows to document evidence**, and no reconciliation/report node. PDF uploads take the text-parser branch even if their pages are scanned. Browser review actions write to Bizmatic only.

## Proposed AP audit flow

```mermaid
flowchart TD
    Admin["Authorized administrator"] --> Scope["Organization and audit scope"]
    Scope --> Mapping["Catalog snapshot and approved mapping"]
    ERP["ERP: restricted read-only role"] --> Import["Bounded consistent import"]
    Mapping --> Import
    Import --> Staged["Source rows, identity and control totals"]
    Staged --> Valid{"Complete and valid?"}
    Valid -->|No| Blocked["Blocked run with reasons"]
    Valid -->|Yes| Canonical["Versioned AP headers and lines"]
    Upload["Authorized document upload"] --> Evidence["Private immutable originals and hashes"]
    Evidence --> Extract["Page text or OCR job"]
    Extract --> Structured["Typed fields and page evidence"]
    Structured --> Review["Human correction and selected revision"]
    Review --> Match["Links and quantity allocations"]
    Canonical --> Match
    Match --> Rules["Versioned deterministic rules"]
    Rules --> Findings["Findings and unable-to-conclude results"]
    Findings --> Decisions["Reviewer decisions and reasons"]
    Decisions --> Report["Frozen report and evidence manifest"]
```

All mutations after the ERP node target Bizmatic's own database or private evidence storage. **No arrow returns to the ERP.** The web app must not possess a source write role. The report includes import failures, unreviewed/ambiguous matches and missing evidence so omissions cannot produce a misleading clean result.

## Boundaries and payloads

| Boundary | Allowed payload | Required control |
| --- | --- | --- |
| Browser → Bizmatic | Uploads, mapping selections, review decisions | Authentication, role and organization scope, CSRF, quotas, optimistic version checks |
| Worker → ERP | Catalog queries and explicit allowlisted SELECT projections | Approved destination, TLS identity, read-only role/transaction, query/runtime budgets, no Django migrations on source |
| ERP → Bizmatic | Allowed source fields plus complete keys and scope | Versioned mapping, consistent import, raw-value provenance, rejection and control counts |
| Bizmatic → OCR provider | Approved document/page bytes and extraction prompt | Organization/provider approval before dispatch, HTTPS or explicitly approved local endpoint, bounded bytes/pages/cost, sanitized errors |
| Worker → local persistence | Job results, attempts, canonical records and evidence | Idempotent writes; short transactions; committed-result recovery; no hidden partial publish |
| Bizmatic → reviewer/report | Only authorized organization evidence and results | Private downloads, page/field citations, report manifest and immutable decisions |

## Job and audit lifecycle

```mermaid
stateDiagram-v2
    [*] --> Queued
    Queued --> Running: worker claims lease
    Running --> Completed: validated results committed
    Running --> Retryable: transient failure or expired lease
    Retryable --> Queued: bounded backoff
    Running --> Failed: permanent validation failure
    Queued --> Cancelled: authorized cancellation
    Running --> Cancelled: worker acknowledges cancellation
    Completed --> [*]
    Failed --> [*]
    Cancelled --> [*]
```

A job attempt is immutable once terminal. Retry creates an attempt while preserving identity and idempotency. A document may need human review even after its extraction job completes. An audit run must reference completed import and selected extraction revisions; unresolved evidence creates an explicit incomplete finding/coverage state. Report issuance freezes that state. Reprocessing generates a new run linked to the prior run and does not erase prior decisions.
