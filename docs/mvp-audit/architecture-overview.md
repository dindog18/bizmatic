# Architecture overview

## Current architecture

Bizmatic is a server-rendered Django monolith with two installed domain apps. The default application database is SQLite, configurable to PostgreSQL; the external ERP connection is a separate psycopg connection, not a Django database alias. That separation is valuable: source databases are never migration targets in the current connector. [bizmatic_django/bizmatic_django/settings.py:69](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/bizmatic_django/settings.py#L69), [bizmatic_django/db_extraction/services/postgres.py:30](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/db_extraction/services/postgres.py#L30)

`document_extraction` combines original-file storage, extraction orchestration and human Markdown review. Views call services; `util.py` remains both a compatibility entry point and an orchestration module. Work runs within HTTP requests using asynchronous tasks and thread offloading. Concurrency limits apply per batch, not across all web processes. Files live on a configured filesystem path; rows retain that path. [bizmatic_django/document_extraction/util.py:22](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/document_extraction/util.py#L22), [bizmatic_django/document_extraction/services/uploads.py:60](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/document_extraction/services/uploads.py#L60), [bizmatic_django/document_extraction/services/storage.py:18](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/document_extraction/services/storage.py#L18)

`db_extraction` stores connection profiles and relational catalog snapshots. A source lock prevents concurrent refreshes on PostgreSQL application databases; catalog reads happen outside that lock and local persistence is atomic. A failed refresh retains the previous successful snapshot. Credential handling is encapsulated in an encrypted field and external key file. [bizmatic_django/db_extraction/services/extraction.py:65](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/db_extraction/services/extraction.py#L65), [bizmatic_django/db_extraction/fields.py:8](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/db_extraction/fields.py#L8), [bizmatic_django/db_extraction/credentials.py:19](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/db_extraction/credentials.py#L19)

AP and AR are not installed; there is no shared accounting domain, mapping, import, reconciliation or audit-report layer. See [bizmatic_django/accounts_payable/models.py:6](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/accounts_payable/models.py#L6), [bizmatic_django/accounts_receivable/models.py:8](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/accounts_receivable/models.py#L8), and [bizmatic_django/bizmatic_django/settings.py:69](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/bizmatic_django/bizmatic_django/settings.py#L69). Keep the monolith and existing service pattern. Introduce only the boundaries needed to make the audit reproducible; do not replace the frontend with an SPA or introduce microservices for this MVP.

## Proposed boundaries

These are proposed apps/modules, not implemented features.

| Boundary | Owns | Must not own |
| --- | --- | --- |
| `core` (new) | Organization, membership/roles, counterparty/item aliases, currency/UOM references, common provenance helpers | ERP credentials or reconciliation verdicts |
| `db_extraction` | Authorized source identity and revisions, catalog snapshot, mapping versions, import runs, allowlisted source-row snapshots | Arbitrary user SQL or any ERP writes |
| `document_extraction` | Private originals, hashes/pages, raw extraction attempts, typed field revisions, reviewer corrections, document evidence | Accounting truth inferred solely from LLM output |
| `accounts_payable` | Company PO, supplier DR, supplier SI headers/lines and local read-only projections | Supplier payment execution or source mutations |
| `accounts_receivable` | Customer PO, company DR, company SI projections, after AP acceptance | Customer collection automation in MVP |
| `reconciliation` (new) | Audit scope, candidate links, allocations, rule versions, findings/evidence, review events, report manifests | Direct ERP connections or silent source repair |
| Durable job module | Job lease/state, idempotency, progress, bounded retry/cancellation, sanitized failures | Long transactions around provider calls |

Start with a database-backed job record and a separate worker management command, or adopt one maintained queue if operationally preferred. Either choice needs durable leases, idempotent effects and a watchdog. An in-process asyncio task is not a durable job. Use `transaction.on_commit` for enqueue notification and recover undispatched committed jobs; do not assume atomicity across database and filesystem/queue boundaries.

## Minimum model contracts

| Entity | Required fields and invariants |
| --- | --- |
| Organization / Membership | Stable organization ID; user, role (`administrator`, `auditor`, `reviewer`, `viewer`); unique membership; explicit active organization. No implicit fallback to another organization |
| Source revision | Organization, source identity UUID, host/port/database/schema scope, TLS policy, actor/time; credential reference excluded from evidence exports; immutable identity revision per import |
| Mapping version | Organization/source revision, direction AP/AR, canonical schema version, catalog fingerprint, relation/column identifiers, key/join/filter/transform definitions, approver/time, hash; immutable once used |
| Import run / Source record | Scope and consistent source snapshot metadata, mapping version, start/end, counts/control totals/rejections; relation and complete ordered primary key, allowlisted raw values, row hash; unique record identity within an import. No cross-organization links |
| Counterparty / Item / UOM | Canonical identity plus source/organization-scoped aliases; preserve raw identifiers; human-confirmed ambiguous aliases. Never globally merge parties by display name |
| AP header | Kind (`company_po`, `supplier_dr`, `supplier_si`), organization/counterparty, raw and normalized number, date, source identity/revision, currency, net/tax/gross, discounts/charges, cancellation/status. Decimal values; missing distinct from zero |
| AP line | Header FK, stable source line key/order, item/UOM, Decimal quantity/price/discount/tax/net/gross, raw values. Unique line identity per header/import; typed signed returns or an explicit unsupported exception, not coerced positive amounts |
| Document asset / page | Organization, original immutable object key, SHA-256, size, verified MIME, upload actor/time; ordered pages with render hash and rotation. Distinguish same bytes from duplicate accounting transaction |
| Extraction attempt / revision | Asset hash, parser/provider/model/prompt/schema versions, job/attempt ID, status/quality, raw output immutable; correction creates a new revision linked to previous revision, actor and reason |
| Structured field / line | Typed value, original token text, validation state and page/region or text-span locator; confidence is an aid to review, not a posting/approval rule. Unknown/missing stays explicit |
| Record link / Allocation | ERP record/line revision ↔ document field/line revision; method, score, explicit reference, reviewed status; allocations carry matched quantity and UOM conversion version. Conservation checks prevent one DR line being counted twice |
| Audit run / Finding | Organization, AP/AR scope, import and extraction versions, cut-off, ruleset/tolerances, completeness; rule code, severity, expected/observed/delta/unit, explanation operands, evidence links, stable fingerprint per run |
| Review event / Report | Append-only finding decision with actor/time/reason/version; report stores immutable manifest of scope, inputs, findings, decisions and coverage at generation, plus output hash |

Use FKs, `PROTECT` for cited evidence, unique constraints for identities and checks for valid local states. Enforce cross-parent organization consistency in service boundaries and, where practical, composite constraints/triggers on PostgreSQL. `Model.clean()` alone is not an ORM or bulk-write guarantee. Use typed FKs for core evidence relationships rather than generic references that cannot enforce referential integrity. Do not deduplicate ERP imports on invoice number: the same number can be reused by suppliers, branches or years.

## Mapping a real wholesale ERP

No VANS V2 schema was available for this audit. The first mapping must be based on an authorized catalog export and synthetic examples of its relationships. Record each unknown as a configuration decision; never invent table/column names.

1. Define the audit scope: organization/branch, supplier population, document dates, cut-off, cancellation/return handling, timezone, currency and permitted tables/columns.
2. Choose stable source identities, including composite keys. For keyless tables, require an approved identity strategy or reject import. Do not use row order as identity.
3. Describe header/line/master joins with cardinality expectations. Count distinct source keys before and after each join; reject fan-out, orphan lines and ambiguous relationships. Catalog FKs are helpful but do not prove business meaning.
4. Map required fields with a small allowlist of typed transformations. Use psycopg identifier composition for validated schema/table/column names and bound parameters for values. No user SQL, expression `eval`, DDL or unrestricted functions.
5. Preview bounded synthetic or separately authorized records; validate required values, Decimal/date conversion, UOM/currency and control totals. Approval freezes the mapping and schema fingerprint.
6. Import a bounded repeatable-read source snapshot using deterministic keyset pages/server cursors. Keep local import status staged until all selected tables, counts and totals validate; publish the run atomically. Bound transaction duration to avoid prolonged source load.
7. If connection loss destroys the source snapshot, restart as a new import version. Never concatenate fresh pages into an old “consistent” snapshot. Resume only when the same immutable exported snapshot is guaranteed.
8. Detect schema drift before import. Missing/changed required columns or join keys block the mapping; optional changes are visible and require policy. Retain source identity independently of mutable connection profiles.

The importer stores only allowed business fields. A metadata-only source account currently sufficient for inspection may need explicit SELECT grants on the approved ERP relations for row import. Have the source administrator provision those grants outside Bizmatic; do not automatically grant privileges. Reject superuser/bypass-RLS/unsafe roles and document inherited-role limitations. Database permissions and network restrictions are the durable safety boundary; session read-only settings are defense in depth.

## Reconciliation contract

Use pure deterministic functions over validated snapshots. AI may transcribe and propose links; it does not calculate authoritative differences or decide whether a discrepancy is legitimate. Represent every outcome as pass, discrepancy, or unable-to-conclude, with scope and operands.

| Rule family | Required semantics |
| --- | --- |
| ERP ↔ document | Compare each canonical header and line with its selected document revision before comparing PO/DR/SI. Preserve differences on both dimensions |
| Header | Party, document/reference number, date window, currency, cancellation/status, totals; evaluate net and tax separately on a declared basis; absent fields do not equal zero |
| Quantity | Normalize to a declared UOM; aggregate distinct eligible DR allocations against PO quantities and SI allocations against receipts as of cut-off; separate partial fulfilment from overdue/missing evidence |
| Price | Compare invoice versus order unit price on the same net/gross, discount, tax and UOM basis; use Decimal and a versioned rounding/tolerance policy; separate free-of-charge units |
| Missing | Require successful imports and an explicit document submission/cut-off policy. If uploads are incomplete, say “supporting document not supplied”; never assert an ERP transaction is absent from a failed import |
| Duplicates | Separate identical upload hash, repeated import identity, same business-key collision and probable economic duplicate; only the last two are candidate audit findings, with human judgment |
| Totals | Recompute line extensions with explicit rounding stage; compare header control totals once. Do not sum header and constituent line findings into double-counted exposure |
| Complex flows | Support split deliveries/invoices and approved many-to-many allocations. Returns/credit notes either use explicit signed typed records or are excluded with visible coverage limits |

Example synthetic fixture: PO 10 units at PHP 1,000 net, DRs 6+4 units, SI 10 units at PHP 1,020 net. Quantity matches; price delta is PHP 20/unit and PHP 200 net exposure. A separate header total discrepancy must not add another PHP 200 exposure. With only the first DR at an earlier cut-off, 4 units may be open fulfilment; it is not automatically missing receipt evidence. An invoice before receipt can require investigation depending on approved timing policy.

Document review and finding review are different: selecting a correct transcription does not validate the business transaction. In the finding UI label actions **Confirm finding**, **Dismiss finding**, **Investigate**; “approve” means confirm the finding, never approve a payment. Require a reason and re-review when referenced inputs change. Supersede old audit runs rather than silently rewriting issued reports.

## External technical references

Design recommendations above were checked against primary documentation; the repository itself supplies implementation evidence. PostgreSQL repeatable-read provides a stable transaction snapshot: [transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html). TLS modes have different identity guarantees: [libpq SSL](https://www.postgresql.org/docs/18/libpq-ssl.html). Short transaction boundaries and post-commit work are described in [Django transactions](https://docs.djangoproject.com/en/6.0/topics/db/transactions/). Deployment controls follow the [Django deployment checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/). Django references are conceptual 6.0 documentation; the tested repository dependency is 6.1.2 and must govern API compatibility.
