# Testing strategy

## Executed baseline

At the inspected commit, the existing **65 tests passed** on Python 3.14.8 / Django 6.1.2 with the pinned root requirements and an isolated in-memory SQLite application database. No ERP or real provider was contacted. This verifies the existing tested contracts, including some unsafe contracts such as anonymous source access; it is not an MVP completion test.

| Existing suite | Tests | Coverage provided | Important omissions |
| --- | --- | --- | --- |
| `document_extraction/tests.py` | 13 | Read-only GET/HEAD queries, routes/rendering, search/filter/pagination, parent IDs, original download, server Markdown safety | Browser runtime, authentication/tenant security, scanned PDF correctness |
| `document_extraction/test_records.py` | 12 | CRUD, review/accuracy flags, optimistic edit conflicts, processing guards, CSRF and deletion behavior | Actor/reason history, immutable provenance, approval eligibility, real concurrent transactions |
| `document_extraction/test_uploads.py` | 16 | Upload/rerun persistence, synthetic OpenAI/Ollama responses, shared batch concurrency, failure/cancellation and history | Real OCR, page fallback, resource limits, global quotas, worker crashes, other provider contracts |
| `document_extraction/test_environment.py` | 6 | Environment precedence and settings selection | Production deployment/secrets/backup recovery |
| `db_extraction/tests.py` | 7 | Encrypted storage/rotation-like rewrites, key safety, form handling, fixture restriction, constraint uniqueness, legacy credential migration | Real source permission/TLS/catalog compatibility, source role rejection, network policy |
| `db_extraction/test_workflows.py` | 11 | Connection forms, mocked refresh, composite key persistence, rollback/history, local deletion, CSRF | Actual catalog SQL, consistent source row import, real locking/races, authorization |
| AP/AR | 0 | Placeholder test modules only | All accounting behavior |

CI currently runs only the first four suites (47 tests). See [.github/workflows/ci.yml:39](https://github.com/dindog18/bizmatic/blob/f8c1bec08a22ac27cd77b7349f85368983fc1092/.github/workflows/ci.yml#L39). The database workflow mocks `inspect_database`, and form tests mock `test_connection`; these tests validate persistence/UI contracts, not actual PostgreSQL catalog behavior. No line/branch coverage tool is configured and no coverage percentage was measured. Unused dependencies and vendored JavaScript were not vulnerability-cleared by this test run.

## Required test layers

| Layer | What to verify | Test environment |
| --- | --- | --- |
| Unit/property | Decimal transforms, keys/aliases, mapping compiler, pure reconciliation rules, allocation conservation, deterministic explanations | Synthetic in-memory values; no network |
| Database/model | Constraints, migration data preservation, tenant relationships, immutable revisions, protected evidence, idempotency | Disposable PostgreSQL app database; SQLite retained for fast supported subset |
| Source integration | PostgreSQL 14 minimum and a declared pilot version; catalog definitions/permissions; ordered composite keys; source read-only policy, TLS, schema drift; bounded row snapshots | Dedicated disposable PostgreSQL source with synthetic tables/roles; never production ERP |
| Provider contract | All supported payload and result shapes, usage/truncation/empty/error/429/timeout; policy and redaction | HTTP mocks/captured synthetic responses; paid calls separately authorized |
| Document quality | Digital/scanned/mixed/rotated PDFs, multi-page lines, faint scans, table alignment, handwritten annotations, unreadable values | Generated synthetic corpus first; real de-identified corpus only after authorization |
| HTTP/security | Login, role, tenant, CSRF, nested IDs, original/report downloads, error redaction and source endpoint policy | Django clients with two organizations and explicit roles |
| Concurrency/recovery | Two workers claim same job; same source refresh twice; review/edit races; crash after storage/before registration/after provider/before commit; watchdog retry | PostgreSQL `TransactionTestCase` or process-level worker harness; independent connections |
| Browser/E2E | Source onboarding, mapping preview, upload, jobs, field correction, comparison, finding decisions, report; keyboard and narrow viewport | Supported browser with synthetic fixtures and stub providers |
| Operations | Fresh install, migrations, static/private files, TLS, secrets, health, metrics, backup/restore, key loss/rotation | Disposable deployment matching the pilot topology |

Do not use source DML attempts as a permission test on a customer database. In disposable source integration tests, a separate fixture administrator may create schema and synthetic rows; application connector calls must be captured and restricted to allowed reads/session settings. Validate privilege denial on the disposable service only. Assert no source mutation during the entire audit flow.

## Minimum accounting corpus

| Fixture | Expected outcome |
| --- | --- |
| Matching PO/DR/SI with matching document fields | No discrepancy; complete evidence and scope recorded |
| ERP says 10 units, document says 9 | ERP/document quantity discrepancy cites the exact line/page |
| PO 10; DR 6 then DR 4; SI 10 | Full quantity match after both eligible receipts; no duplicate consumption |
| PO 10; only DR 6 before expected completion | Partial/open state under cut-off policy; no invented missing-transaction certainty |
| PO 10; DR 12 | Overdelivery of 2 units with exact UOM and scope |
| PO net price 1,000; SI net price 1,020 on 10 units | PHP 200 net price exposure once, not doubled by header finding |
| Gross/net price mix, VAT, header discount, freight | Correct basis normalization or explicit unsupported/unknown outcome |
| Packs of 12 vs individual units | Correct versioned conversion; unknown conversion requires review |
| Same supplier invoice number from different suppliers/years/branches | Distinct identity; no automatic duplicate assertion |
| Same source key reimported / identical file re-uploaded | Idempotent source import / duplicate asset indication; not automatically a duplicate accounting transaction |
| Distinct records with same business operands | Explainable probable duplicate candidate for human review |
| Missing SI/DR, absent upload, failed import | Separate missing-record, supporting-document-not-supplied and incomplete-population states |
| Duplicate SKU lines and multiple PO references | Explicit allocations; no greedy name-based match or Cartesian fan-out |
| Return/credit/cancellation | Supported signed policy or visible scope exclusion; never silently netted away |
| Price/quantity exactly at tolerance and just outside | Correct boundary comparison, rule version and Decimal rounding |
| Empty, truncated, unreadable or contradictory extraction | Cannot approve as valid structured evidence; requires correction or investigation |
| Backdated/late document and source change during import | Correct audit cut-off and stable snapshot; later evidence supersedes run |
| Changed evidence after reviewer decision | New/superseded result requires re-review; original report stays stable |
| Cross-organization IDs and formula-like CSV fields | Access denied; report fields exported as safe text |

Add invariants: reordering input rows does not change results; quantities allocated never exceed available eligible quantities; repeated execution of identical inputs/rules has identical outcomes; total impact is not double-counted; missing values never become zero; adding an unrelated supplier does not alter another supplier's matches.

## OCR and matching acceptance

Do not set a universal OCR “accuracy” number without a labelled corpus. Measure exact field correctness for supplier/document number/date/currency/amount and line count/quantity/price; track omitted lines separately from spelling errors. Measure candidate-link precision and abstention, and how many material errors pass unnoticed. For the first pilot require **all material fields used in reconciliation to be human reviewed**, zero ambiguous automatic links, and 100% expected outcomes on the deterministic golden accounting corpus. Record corpus size, document families and limitations. Relax manual review only after a separate measured decision.

## Performance and operational gate

Start with a declared synthetic trial budget (proposal, not measured): 1,000 headers, 10,000 lines, 200 documents / up to 20 pages each, at most three concurrent users. Establish acceptable request latency, worker duration, peak memory, source query duration and provider spend before running it; tune the declared pilot scope to the actual hardware. Use bounded imports and pagination instead of guessing enterprise scale. A long source snapshot must have a duration limit and abort safely without claiming completeness.

Release checks: all P0 tasks closed; migrations preserve old evidence; every deterministic fixture passes; two-tenant negative tests pass; interrupted work is recovered; source SQL is read-only; report reproduces its manifest; synthetic restore recovers data/files/key; accounting owner signs the walkthrough. Record any unsupported accounting case as an explicit report exclusion. No deploy should depend on the mere existence of a green unit test job.
