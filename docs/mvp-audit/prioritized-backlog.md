# Prioritized implementation backlog

These are proposed changes, not changes made by this audit. Each task targets one small PR; B09 and B21 explicitly permit two sequential PRs when needed. Estimates are engineering workdays including tests/review preparation, not calendar commitments. They assume access to agreed synthetic schemas; unknown VANS V2 relationships or business decisions can increase effort.

Rank balances **business value (1–5), MVP gate, dependencies, effort and security/operational risk**. P0 blocks safe use or evidence retention; P1 builds the AP vertical slice; P2 here means the explicitly deferred AR slice, still required to claim the full requested AP/AR scope. P0 operational work B27–B28 may start earlier once dependencies exist and must finish before a real-data pilot. Order is a dependency-aware recommendation, not a mandate to execute every row serially.

Business benefit is tied to the evidence-backed issue IDs in [gap analysis](mvp-gap-analysis.md). All tasks inherit this definition of done: only authorized organization data is accessible; no source mutation/credentials/customer fixtures in diff; relevant tests and migration checks pass; code, migrations and operator/user notes agree; PR is reviewed and mergeable. The task-specific completion criterion below is additional.

| Rank / ID | Task | Value | MVP gate | Effort | Risk | Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| 01 / [B01](#b01) | CI covers the actual application | 5/5 | P0 | 1–2 days | High | None |
| 02 / [B02](#b02) | Require login and explicit roles for workspace routes | 5/5 | P0 | 1–2 days | Critical | B01 |
| 03 / [B03](#b03) | Preserve historical text logs during upgrades | 5/5 | P0 | 1–2 days | High | B01 |
| 04 / [B04](#b04) | Introduce organization and membership ownership | 5/5 | P0 | 2–3 days | High | B02 |
| 05 / [B05](#b05) | Scope every query, form and action to organization | 5/5 | P0 | 2–3 days | Critical | B04 |
| 06 / [B06](#b06) | Harden the read-only source connection boundary | 5/5 | P0 | 2–3 days | High | B05 |
| 07 / [B07](#b07) | Bound and validate document intake | 5/5 | P0 | 2–3 days | High | B05 |
| 08 / [B08](#b08) | Control provider routing and redact errors | 5/5 | P0 | 1–2 days | High | B05 |
| 09 / [B09](#b09) | Make extraction and refresh jobs durable | 5/5 | P0 | 3–4 days | High | B05, B07, B08 |
| 10 / [B10](#b10) | Make originals and extraction revisions traceable | 5/5 | P0 | 2–3 days | High | B04, B07, B09 |
| 11 / [B11](#b11) | Define canonical AP headers, lines and shared dimensions | 5/5 | P1 | 2–3 days | High | B04, B10 |
| 12 / [B12](#b12) | Version mappings and detect source schema drift | 5/5 | P1 | 2–3 days | High | B06, B11 |
| 13 / [B13](#b13) | Build mapping preview and approval workflow | 4/5 | P1 | 2–3 days | Medium | B12 |
| 14 / [B14](#b14) | Import a bounded consistent ERP snapshot | 5/5 | P1 | 3–4 days | High | B09, B12 |
| 15 / [B15](#b15) | Normalize accounting identifiers and values | 5/5 | P1 | 2–3 days | High | B11, B12 |
| 16 / [B16](#b16) | Route scanned and mixed PDFs through page OCR | 5/5 | P1 | 2–3 days | High | B07, B08, B09, B10 |
| 17 / [B17](#b17) | Extract validated PO/DR/SI fields with evidence | 5/5 | P1 | 3–4 days | High | B10, B11, B15, B16 |
| 18 / [B18](#b18) | Link source records and documents conservatively | 5/5 | P1 | 2–3 days | High | B14, B15, B17 |
| 19 / [B19](#b19) | Persist audit runs, findings and protected evidence | 5/5 | P1 | 2–3 days | High | B10, B11, B14, B17 |
| 20 / [B20](#b20) | Implement header and control-total reconciliation | 5/5 | P1 | 2–3 days | High | B15, B18, B19 |
| 21 / [B21](#b21) | Implement line allocations and quantity/price rules | 5/5 | P1 | 3–4 days | High | B20 |
| 22 / [B22](#b22) | Detect missing evidence and duplicate transactions | 5/5 | P1 | 2–3 days | High | B19, B21 |
| 23 / [B23](#b23) | Record human finding decisions and investigation | 5/5 | P1 | 1–2 days | High | B05, B19 |
| 24 / [B24](#b24) | Build the evidence-first audit workspace | 5/5 | P1 | 2–3 days | Medium | B18, B20, B21, B22, B23 |
| 25 / [B25](#b25) | Export a reproducible scoped audit report | 5/5 | P1 | 2–3 days | High | B22, B23, B24 |
| 26 / [B26](#b26) | Validate accounting/OCR correctness on a labelled corpus | 5/5 | P1 | 2–3 days initially | High | B14, B17, B22, B25 |
| 27 / [B27](#b27) | Package production configuration and operations | 5/5 | P0 before pilot | 2–3 days | High | B01, B02, B06, B08, B09 |
| 28 / [B28](#b28) | Prove backup, key recovery and evidence retention | 5/5 | P0 before pilot | 2–3 days | High | B10, B19, B25, B27 |
| 29 / [B29](#b29) | Add canonical AR documents and migrations | 4/5 | P2 after AP pilot; required for full AP/AR scope | 2–3 days | Medium | B11, B26 |
| 30 / [B30](#b30) | Map and import the AR source population | 4/5 | P2 after AP pilot; required for full AP/AR scope | 2–3 days | High | B12, B13, B14, B15, B29 |
| 31 / [B31](#b31) | Deliver and validate the AR reconciliation slice | 4/5 | P2 after AP pilot; required for full AP/AR scope | 3–4 days | High | B17, B18, B21, B22, B23, B24, B25, B30 |

<a id="b01"></a>

## B01 — CI covers the actual application

**Affected apps:** project / both extraction apps. **Dependencies:** None. **Issues/business risk:** G19, G21, G23; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Run both active apps in CI; add an isolated PostgreSQL application/source service test job while retaining fast SQLite tests. Correct README/CONTRIBUTING write-action claims and make root requirements authoritative.

**Acceptance criteria:** CI collects the existing 65 tests; PostgreSQL smoke tests exercise real catalog queries and composite FKs; neither source nor provider credentials are required.

**Tests required:** Clean install, dependency check, system and migration checks, both suites; tests reject all network except the disposable source service.

**Definition of done:** Required checks are documented and enforced in repository configuration where authorized; no passing SQLite result is described as PostgreSQL coverage.

<a id="b02"></a>

## B02 — Require login and explicit roles for workspace routes

**Affected apps:** core (new), document_extraction, db_extraction. **Dependencies:** B01. **Issues/business risk:** G01; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add minimal Django session login/logout and shared permission helpers. Restrict source management to administrators, extraction/review writes to explicit roles, and originals to authorized readers. Include admin and service entry points.

**Acceptance criteria:** Anonymous users cannot enumerate documents, download originals, invoke OCR, inspect schemas or mutate sources; logged-in viewers cannot write; safe methods remain read-only.

**Tests required:** Route matrix for anonymous/viewer/auditor/reviewer/admin, CSRF and method tests; replace current tests that expect anonymous source writes.

**Definition of done:** Every existing workspace route has a documented permission; no open alternate original or action URL remains. Organization scoping follows in B04–B05.

<a id="b03"></a>

## B03 — Preserve historical text logs during upgrades

**Affected apps:** document_extraction. **Dependencies:** B01. **Issues/business risk:** G04; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Inventory deployed migration states without customer content. Design a preservation path for 0001 data and a recovery runbook for already-applied 0002. If history is deployed, do not casually rewrite it: provide an approved pre-upgrade export/import or replacement migration strategy with backup checks.

**Acceptance criteria:** A synthetic populated 0001 database upgrades with text, errors, document links and timestamps intact; fresh installs still work. Already-dropped data is explicitly recoverable only from a backup/export.

**Tests required:** Disposable migration tests for fresh and populated histories; failure before migration does not discard evidence; validate recovery with synthetic backup.

**Definition of done:** Reviewed migration-state decision and rehearsal evidence accompany the PR; no production migration is executed by this task.

<a id="b04"></a>

## B04 — Introduce organization and membership ownership

**Affected apps:** core (new), document_extraction, db_extraction. **Dependencies:** B02. **Issues/business risk:** G02; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Create Organization/Membership roles and organization FKs on source, batch and document roots. Use staged nullable/backfill/non-null migrations; existing records require an explicit owner assignment, not a guessed tenant.

**Acceptance criteria:** All new roots require organization ownership; memberships are unique; backfill refuses ambiguous data; single-organization pilot setup is explicit.

**Tests required:** Migration rehearsal, root ownership constraints, membership uniqueness and owner assignment failure cases.

**Definition of done:** Schema/data backfill plan is reviewed, with generated migrations; B05 must land before access is opened to multiple organizations.

<a id="b05"></a>

## B05 — Scope every query, form and action to organization

**Affected apps:** core, document_extraction, db_extraction. **Dependencies:** B04. **Issues/business risk:** G01, G02; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Pass authorized organization context through view/service/query boundaries, form choices, admin and job payloads. Check cross-parent ownership; prevent client-supplied organization IDs from widening scope.

**Acceptance criteria:** Two organizations with similar source names and document IDs cannot observe or modify each other, including downloads, counts, batch assignment and nested URLs.

**Tests required:** Two-tenant negative tests for list/detail/actions/originals/admin/form relations and forged IDs; query-count checks for normal lists.

**Definition of done:** Permission/tenant matrix passes on PostgreSQL and SQLite; all future services receive an explicit scope contract.

<a id="b06"></a>

## B06 — Harden the read-only source connection boundary

**Affected apps:** db_extraction, core. **Dependencies:** B05. **Issues/business risk:** G03, G25; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add approved destination and TLS policy; require a dedicated restricted role, reject obviously unsafe role flags and check read-only session state. Bind credentials to immutable source identity revisions; require explicit handling on host changes. Use bounded catalog/privilege probes, never trial writes on an ERP.

**Acceptance criteria:** Unapproved hosts/sockets/multihost forms are rejected before connection; remote TLS identity is verified; stored credentials cannot silently follow a changed destination; snapshots retain safe source revision identifiers.

**Tests required:** Mock egress and DNS/IPv6 cases; disposable PostgreSQL role/read-only/timeout tests; wrong certificate rejection; no DML emitted by application connector.

**Definition of done:** Admin provisioning instructions list exact table/column access needs and prohibited privileges; no source credentials appear in logs/fixtures.

<a id="b07"></a>

## B07 — Bound and validate document intake

**Affected apps:** document_extraction. **Dependencies:** B05. **Issues/business risk:** G07, G16, G22; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Allowlist supported pilot formats using actual decoders/signatures. Enforce per-file, batch, page/pixel and expanded-archive budgets before extraction; coordinate proxy body limits; resolve private storage roots and containment. Reject unsupported legacy formats early.

**Acceptance criteria:** Oversized/spoofed/corrupt files receive safe validation errors before provider dispatch; successful files retain original bytes; filesystem paths are not exposed in normal UI.

**Tests required:** Synthetic wrong MIME, corrupt/encrypted PDF, oversized page/image/archive metadata, path/symlink containment and batch quota cases; do not construct dangerous resource bombs.

**Definition of done:** Limits are configurable, documented and visible before upload; cleanup handles rejected/temp objects without touching retained evidence.

<a id="b08"></a>

## B08 — Control provider routing and redact errors

**Affected apps:** document_extraction, core. **Dependencies:** B05. **Issues/business risk:** G08, G23; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Start with one approved provider/model per organization and an explicit data-routing policy. Gate dispatch, enforce endpoint/budget policy and replace raw errors with codes/correlation IDs; keep redacted diagnostics separate. Preserve existing adapters without claiming untested model support.

**Acceptance criteria:** Unapproved external dispatch is blocked; no silent vendor fallback; injected fake secrets/content in provider errors never appear in UI, stored errors or logs.

**Tests required:** Mock each adapter response shape including empty/truncated/429/timeout/error payload; policy-denial tests; redaction assertions using synthetic markers.

**Definition of done:** Provider decision is auditable; operators have safe diagnostic codes and configurable budgets; no live paid call is required in CI.

<a id="b09"></a>

## B09 — Make extraction and refresh jobs durable

**Affected apps:** document_extraction, db_extraction, job module. **Dependencies:** B05, B07, B08. **Issues/business risk:** G14, G15; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Persist job/attempt IDs, idempotency key, lease/heartbeat and terminal outcome; run a separate worker and watchdog. Keep file/provider failures independent, use bounded retry only for transient errors, and return a job URL quickly. Split into job/worker and route-switch PRs if needed.

**Acceptance criteria:** Worker termination recovers after lease expiry; duplicate submission creates no duplicate logical attempt; a bad file does not cancel unrelated documents; progress survives browser refresh.

**Tests required:** PostgreSQL concurrent claim tests, crash-after-commit/retry, quota/rate-limit, partial batch success, cancelled work and source-refresh supersession.

**Definition of done:** Worker startup/recovery contract is documented; no route relies on a long provider request; terminal attempts and partial failures remain visible.

<a id="b10"></a>

## B10 — Make originals and extraction revisions traceable

**Affected apps:** document_extraction, core. **Dependencies:** B04, B07, B09. **Issues/business risk:** G05, G06, G13, G16; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Persist asset hash/size/MIME and immutable raw attempts with job/model/prompt/parser versions. Corrections append revisions with actor/reason; select an explicit usable revision. Add private verified original access and forbid destructive evidence edits/deletes in ordinary workflows.

**Acceptance criteria:** Original bytes and raw provider output remain unchanged after correction/rerun; conflicting accurate flags cannot implicitly select a result; failed/empty content cannot become a reviewed canonical extraction.

**Tests required:** Hash mismatch/missing original, append-only revision, supersession, deletion protection, stale selection and actor/reason tests.

**Definition of done:** Existing logs migrate without loss; legacy edited content is labelled as legacy/unverifiable rather than invented raw output; evidence APIs expose stable IDs.

<a id="b11"></a>

## B11 — Define canonical AP headers, lines and shared dimensions

**Affected apps:** core, accounts_payable. **Dependencies:** B04, B10. **Issues/business risk:** G09, G12, G24; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Install AP with versioned company PO/supplier DR/supplier SI and line models, counterparty/item/UOM/currency references and provenance IDs. Use Decimal fields, explicit null/status semantics, scoped source identities and database constraints. Keep payments outside this slice.

**Acceptance criteria:** Synthetic PO/DR/SI retains line keys, raw references, amounts and source provenance; duplicate source identity or cross-organization relation fails; reused supplier invoice numbers remain valid separate identities.

**Tests required:** Model constraints/migrations, Decimal precision, optional-versus-zero, distinct counterparty numbers, composite keys, returns policy and deletion protection.

**Definition of done:** Schema contract and examples are reviewed by an accounting owner; AP is installed with real migrations, not an empty Transaction placeholder.

<a id="b12"></a>

## B12 — Version mappings and detect source schema drift

**Affected apps:** db_extraction, accounts_payable. **Dependencies:** B06, B11. **Issues/business risk:** G10, G24, G25; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add mapping versions tied to catalog/source revisions, required canonical fields, ordered source keys, joins/cardinality, filters and allowlisted typed transforms. Validate mapped identifiers against catalog; freeze approved versions; compute a fingerprint and drift report.

**Acceptance criteria:** Invalid types/keys/unknown identifiers and fan-out-prone joins are rejected; used versions cannot mutate; missing required columns block import.

**Tests required:** Synthetic catalog mappings for composite keys, absent FK, quoted identifiers, excluded schemas, nullable fields, drift and immutable approval.

**Definition of done:** JSON/schema contract and API examples are stable enough for independent importer/UI work; no arbitrary SQL execution feature exists.

<a id="b13"></a>

## B13 — Build mapping preview and approval workflow

**Affected apps:** db_extraction frontend/services. **Dependencies:** B12. **Issues/business risk:** G10, G21; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Create a server-rendered mapping editor and bounded preview using the shared validated query compiler. Show source/canonical fields, joins, counts, nulls and rejection reasons; require explicit approval. Use synthetic data until a scoped real-source preview is separately authorized.

**Acceptance criteria:** Administrator can configure and preview the three AP document kinds, see why a required field is invalid, and approve a frozen mapping without writing to source.

**Tests required:** Role/tenant and CSRF tests, preview limit/parameterization, duplicate join/cardinality rejection, browser keyboard/error-flow test.

**Definition of done:** A synthetic source can be mapped end-to-end; editor never accepts SQL strings or claims that metadata visibility guarantees row access.

<a id="b14"></a>

## B14 — Import a bounded consistent ERP snapshot

**Affected apps:** db_extraction, accounts_payable. **Dependencies:** B09, B12. **Issues/business risk:** G10, G13, G25; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Build SELECT-only import over approved projections with repeatable-read, stable keyset iteration, source-row keys/hashes and import manifest. Stage canonical rows, track control counts/totals/rejections and publish only when complete. Restart a new version after loss of source snapshot.

**Acceptance criteria:** Repeated import is idempotent within the declared run; composite keys survive; failed pages cannot appear as a complete audit population; imports never execute ERP mutations.

**Tests required:** Disposable PostgreSQL multi-table snapshot with concurrent source changes, row limits, permissions, connection interruption, join fan-out and replay; reconcile expected counts/control totals.

**Definition of done:** Import identity, consistency boundary and load budget are documented; the successful manifest and rejected rows are viewable with organization scope.

<a id="b15"></a>

## B15 — Normalize accounting identifiers and values

**Affected apps:** core, accounts_payable, db_extraction. **Dependencies:** B11, B12. **Issues/business risk:** G10, G12; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Implement versioned Decimal/date/number/UOM/currency normalization and approved counterparty/item aliases. Preserve raw values and distinguish uncertainty; prevent implicit float conversion, removal of meaningful leading zeros and silent currency conversion.

**Acceptance criteria:** Same source values normalize deterministically; ambiguous dates/items/UOM enter a review/rejection queue; all conversions cite a rule version.

**Tests required:** Leading zeros, Unicode, timezone cut-off, decimal comma/grouping, discounts, VAT basis, pack conversions, free units and negative returns cases.

**Definition of done:** Canonical transformations have golden inputs/outputs and documented business decisions; import/document schema use the same functions.

<a id="b16"></a>

## B16 — Route scanned and mixed PDFs through page OCR

**Affected apps:** document_extraction. **Dependencies:** B07, B08, B09, B10. **Issues/business risk:** G11; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Classify usable text per page, render only pages requiring OCR, and preserve page order/rotation/hashes. Reject or quarantine encrypted/corrupt/unsupported files. Treat empty text and unreadable pages as review failures, never successful accounting extraction.

**Acceptance criteria:** Text-only, scanned and mixed PDFs produce page evidence; a blank PDF cannot show usable completion; repeated headers and page continuation remain identifiable.

**Tests required:** Synthetic raster PDF, mixed pages, rotated scan, blank page, encrypted/corrupt input, page limit and provider retry with mocks; no accuracy claim based on mocks.

**Definition of done:** Page metadata and quality states feed B17; actual OCR accuracy is later measured with approved labelled corpus B26.

<a id="b17"></a>

## B17 — Extract validated PO/DR/SI fields with evidence

**Affected apps:** document_extraction, accounts_payable. **Dependencies:** B10, B11, B15, B16. **Issues/business risk:** G06, G12, G13; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Parse/transcribe into a versioned typed AP schema with document kind, parties/references, dates, amounts and lines. Attach page/region or text-span evidence; validate arithmetic and completeness; add field corrections as new revisions.

**Acceptance criteria:** No invalid/unsupported response silently populates canonical amounts; each material value has evidence or an explicit missing flag; a human can correct and select a revision.

**Tests required:** Schema/Decimal validation, omitted lines, multi-page continuation, prompt-injection text, hallucinated/contradictory totals, provider truncation and stale correction.

**Definition of done:** Structured revision contract is frozen for matching; human-labelled examples explain all validation states; model confidence alone never approves values.

<a id="b18"></a>

## B18 — Link source records and documents conservatively

**Affected apps:** reconciliation, core. **Dependencies:** B14, B15, B17. **Issues/business risk:** G17; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Prefer explicit source references and scoped party/document numbers; propose weighted candidates only as review aids. Save match evidence/method and approved aliases; surface unmatched/ambiguous cases and manual link correction history.

**Acceptance criteria:** Same number across suppliers/branches does not auto-link; many candidates require review; source/document revisions are retained; a manual correction supersedes prior links.

**Tests required:** Exact/leading-zero/ambiguous number cases, item aliases, missing references, cancelled records, different currencies and cross-tenant candidates.

**Definition of done:** Matching outcomes and abstention policy are documented; no fuzzy score alone creates an authoritative accounting match.

<a id="b19"></a>

## B19 — Persist audit runs, findings and protected evidence

**Affected apps:** reconciliation. **Dependencies:** B10, B11, B14, B17. **Issues/business risk:** G05, G18, G24; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add AuditRun scope/manifests, ruleset versions, Finding typed operands/severity/fingerprint and evidence FKs; protect cited revisions. Represent incomplete/unable-to-conclude separately from matched and discrepancy states.

**Acceptance criteria:** Every finding resolves to fixed source and document versions; rerunning identical inputs produces stable rule fingerprints; partial import prevents a clean run.

**Tests required:** Immutability, uniqueness/idempotency, cross-parent scope constraints, deleted evidence rejection and run-state transitions.

**Definition of done:** Rule engine contracts are published with synthetic fixture builders for B20–B22; findings contain no mutable display-only provenance.

<a id="b20"></a>

## B20 — Implement header and control-total reconciliation

**Affected apps:** reconciliation, accounts_payable. **Dependencies:** B15, B18, B19. **Issues/business risk:** G17; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add pure rules for ERP/document party, number, dates, reference, status, currency and net/tax/gross totals; version tolerances/rounding. Check within-document arithmetic and PO/DR/SI reference chains with missing-field abstention.

**Acceptance criteria:** Each discrepancy states expected/observed/delta and evidence; differing tax basis is not labelled a price error without normalization; replay is deterministic.

**Tests required:** Header golden cases for tax-inclusive/exclusive prices, discounts/charges, missing totals, cancellations, date windows and tolerance boundaries.

**Definition of done:** Rules and explanations reviewed by accounting owner; every supported rule has positive, negative and unable-to-conclude cases.

<a id="b21"></a>

## B21 — Implement line allocations and quantity/price rules

**Affected apps:** reconciliation, accounts_payable. **Dependencies:** B20. **Issues/business risk:** G17; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Model explicit line allocations for split receipts/invoices and compare normalized quantities/prices. Enforce allocation conservation and cut-off policies; compute distinct monetary impact without duplicate header/line exposure. Split allocation schema and rules into separate PRs if review size grows.

**Acceptance criteria:** PO 10/DR 6+4/SI 10 matches quantity; a price increase yields exact Decimal exposure once; one receipt line cannot satisfy multiple obligations beyond its quantity.

**Tests required:** Partial/multiple/overdelivery, duplicate SKU lines, free units, pack conversion, returns exclusion or signed policy, rounding and concurrent allocation updates.

**Definition of done:** Golden line corpus and conservation invariants pass on PostgreSQL; ambiguous allocation stays investigated instead of guessed.

<a id="b22"></a>

## B22 — Detect missing evidence and duplicate transactions

**Affected apps:** reconciliation, accounts_payable. **Dependencies:** B19, B21. **Issues/business risk:** G17, G18; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add completeness/cut-off-aware missing-record/document rules and distinct duplicate types. Use hashes for upload identity, keys for import identity, scoped business keys and explainable candidates for transaction duplicates.

**Acceptance criteria:** Incomplete import/upload never generates definitive “ERP missing”; duplicate file and duplicate transaction are distinct; legitimate repeated numbers or partial invoices are not automatically rejected.

**Tests required:** Incomplete population, late documents, exact re-upload, reimport, supplier-number collision, probable duplicate and valid split-invoice cases.

**Definition of done:** Every duplicate/missing finding states scope and confidence limitations; reviewer can trace both sides and correct candidate links.

<a id="b23"></a>

## B23 — Record human finding decisions and investigation

**Affected apps:** reconciliation, core. **Dependencies:** B05, B19. **Issues/business risk:** G06, G18; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Create append-only confirm/dismiss/investigate events with actor, reason, timestamps and expected finding version. Keep document extraction review separate. Reopen or supersede decisions on changed evidence/rules.

**Acceptance criteria:** Only permitted reviewers decide; missing reason or stale version fails; “confirm” approves the finding, never a supplier payment; prior decisions remain readable.

**Tests required:** Role/tenant checks, legal state transitions, simultaneous reviews, stale evidence, repeated decision submission and immutable event history.

**Definition of done:** Review policy and labels are explicit; no decision mutates ERP or hides unresolved findings from reports.

<a id="b24"></a>

## B24 — Build the evidence-first audit workspace

**Affected apps:** reconciliation frontend, document_extraction frontend. **Dependencies:** B18, B20, B21, B22, B23. **Issues/business risk:** G18, G21, G22; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add an audit setup checklist, completeness status and discrepancy inbox with source/document/PO-DR-SI comparison, line/page links and review actions. Keep calculations server-side; explain failed imports and ambiguous links in business language.

**Acceptance criteria:** Auditor can find a discrepancy, inspect both operands and original page, investigate/confirm/dismiss and resume later; tables paginate and keyboard actions work.

**Tests required:** Django view/role tests plus browser E2E for one complete audit, incomplete data, slow job, retry, mobile layout and keyboard navigation.

**Definition of done:** Synthetic wholesale walkthrough completes without shell/admin intervention after initial setup; document approval is not presented as accounting approval.

<a id="b25"></a>

## B25 — Export a reproducible scoped audit report

**Affected apps:** reconciliation. **Dependencies:** B22, B23, B24. **Issues/business risk:** G18; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Create frozen report manifests and printable HTML plus safe CSV export before adding rich PDF tooling. Include scope/cut-off/input hashes/versions, coverage/exclusions, findings/evidence references, decisions and unresolved items; neutralize spreadsheet formulas.

**Acceptance criteria:** Same manifest renders the same substantive report after later edits; restricted users cannot download it; source data is untouched; missing evidence and incomplete scope remain visible.

**Tests required:** Manifest snapshot, authorization, formula injection strings, Decimal totals without double counting, stale report detection and export round-trip.

**Definition of done:** Business reviewer approves a synthetic sample report; retained manifests and hashes are protected and downloadable through authorized routes.

<a id="b26"></a>

## B26 — Validate accounting/OCR correctness on a labelled corpus

**Affected apps:** QA across extraction, AP and reconciliation. **Dependencies:** B14, B17, B22, B25. **Issues/business risk:** G19, G22, G23; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Build synthetic labelled golden documents/ERP fixtures and separate approved de-identified real-world validation only when authorized. Measure field/line extraction errors, matching precision/abstention, rule correctness and reviewer time; run a declared pilot-size performance fixture.

**Acceptance criteria:** All deterministic accounting fixtures pass exactly; known exceptions are detected; no silent incomplete run or ambiguous auto-link; measured OCR errors are routed to human review under declared targets.

**Tests required:** Full workflow in disposable PostgreSQL, browser, restart/replay, corrupted input and two-tenant tests; report latency/memory with machine and corpus size.

**Definition of done:** Acceptance record states corpus size/limitations and business sign-off; no “accuracy percentage” is claimed from mocked providers.

<a id="b27"></a>

## B27 — Package production configuration and operations

**Affected apps:** project, jobs, both extraction apps. **Dependencies:** B01, B02, B06, B08, B09. **Issues/business risk:** G15, G20, G22; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Add a reproducible deployment profile with PostgreSQL app DB, production WSGI/ASGI server, worker/watchdog, static/private storage setup, HTTPS/proxy/cookie/secret policy, email decision, health checks and sanitized job metrics. Separate web/worker resource budgets.

**Acceptance criteria:** Production config passes deploy checks or has reviewed environment-specific exceptions; missing secrets fail startup; health is not dependent on a live ERP; worker failure is observable.

**Tests required:** Fresh environment deployment rehearsal, collectstatic, readiness/liveness, request/body limits, worker restart, secret absence and TLS header tests.

**Definition of done:** Versioned deploy/rollback and operator runbook are reviewed; default dev settings cannot accidentally serve the pilot. Actual deployment requires its own authorized rollout.

<a id="b28"></a>

## B28 — Prove backup, key recovery and evidence retention

**Affected apps:** project, db_extraction, document_extraction, reconciliation. **Dependencies:** B10, B19, B25, B27. **Issues/business risk:** G05, G16, G20; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Document and rehearse coordinated application DB/private files/key backups, separated access, key rotation and retention holds. Add safe orphan inventory and approved purge procedure; protect report-referenced assets and sanitize logs.

**Acceptance criteria:** A synthetic report and all referenced originals/source revisions survive restore; encrypted credentials decrypt only with the restored authorized key; held evidence cannot be purged.

**Tests required:** Disposable full restore, wrong/missing key, partially missing files/hash mismatch, rotation failure recovery and retention/hold tests.

**Definition of done:** Restore evidence and agreed RPO/RTO/retention owner are recorded; no customer deletion or production restore occurs in this task.

<a id="b29"></a>

## B29 — Add canonical AR documents and migrations

**Affected apps:** core, accounts_receivable. **Dependencies:** B11, B26. **Issues/business risk:** G09; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Install AR with customer PO/company DR/company SI headers/lines using shared dimensions/provenance. Reuse contracts, not supplier-specific semantics. Keep customer payments out of first AR reconciliation slice.

**Acceptance criteria:** AR has real migrations, scoped identities and typed headers/lines; customer and company reference roles are unambiguous.

**Tests required:** AR constraints, migration paths, source identity, Decimal/returns policy, cross-tenant relationships and AP non-regression.

**Definition of done:** Accounting owner approves AR terminology and scope; no unfinished placeholder is counted as implementation.

<a id="b30"></a>

## B30 — Map and import the AR source population

**Affected apps:** db_extraction, accounts_receivable. **Dependencies:** B12, B13, B14, B15, B29. **Issues/business risk:** G10; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Define approved AR mapping templates only after inspecting authorized VANS V2 metadata. Reuse importer machinery with AR party/reference semantics and independent control totals.

**Acceptance criteria:** Customer PO, company DR and company SI import in one declared scope with exact source identity; unsupported source relationships block approval.

**Tests required:** AR synthetic catalog/source integration, cardinality, composite keys, drift, cancellations and replay tests.

**Definition of done:** AR mapping is signed off separately from AP; no source table names or relationships are inferred without evidence.

<a id="b31"></a>

## B31 — Deliver and validate the AR reconciliation slice

**Affected apps:** accounts_receivable, document_extraction, reconciliation. **Dependencies:** B17, B18, B21, B22, B23, B24, B25, B30. **Issues/business risk:** G17, G18; see the linked issue register for file evidence and business impact.

**Description / suggested implementation:** Extend typed document direction and rule configurations to customer PO/company DR/company SI, including staged delivery/invoicing and documented returns scope. Reuse evidence/review/report contracts with AR-specific fixtures.

**Acceptance criteria:** Independent AR end-to-end corpus detects header/line/missing/duplicate cases, supports reviewer investigation and emits a read-only scoped report without AP regressions.

**Tests required:** AR golden corpus, party direction reversal, many-to-many allocation, missing supporting documents, two-tenant UI/report and AP regression suite.

**Definition of done:** AR acceptance is recorded separately; full AP/AR MVP is claimed only after this task and shared pilot gates pass.

## Scope and sequencing decisions

- AP pilot requires B01–B28; B29–B31 complete the AR portion of the requested workflow. Do not claim AP/AR completion after the first ten PRs.
- The core critical path is scope/security → canonical model/mapping → import and structured documents → links/findings → rules → human review → report → pilot validation. OCR, deployment and source integration testing can overlap once their contracts exist.
- Initial business-owner decisions: approved source/version and read-only grants; AP document meanings; cut-off and missing-evidence policy; VAT/discount/rounding basis; UOM conversion; returns/credit-note handling; duplicate-number policy; reviewer roles; corpus acceptance targets and retention. Implement safe defaults/explicit unsupported states while these are resolved; do not invent VANS V2 semantics.
- Defer payment execution, general ledger replacement, autonomous approval, ERP writes, general SQL builder, speculative multi-ERP connectors and extra OCR vendors. These do not make the first audit correct.
