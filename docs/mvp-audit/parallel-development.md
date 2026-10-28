# Suggested parallel development and worktrees

This is a plan for later implementation. No parallel agents changed application code during this audit. Create one branch/worktree per PR from the same integration baseline, and merge prerequisites before dependent branches rebase. File ownership below is exclusive within a wave; app-wide model/view/template files must not be edited by multiple agents at once.

## Coordination rules

- One integration owner controls `bizmatic_django/bizmatic_django/settings.py`, root URLs, requirements, `.github/workflows/ci.yml` and cross-app contracts. Other agents request an integration patch instead of editing those files concurrently.
- One migration owner per app/wave allocates migration numbers and dependencies. Never let two agents independently create same-app migrations and resolve it by renaming files without reviewing the migration graph.
- Merge shared contracts first: organization context, job payload, source identity/mapping schema, evidence revision, canonical AP schema and findings/rule interfaces.
- Tests/fixtures are owned per module; shared fixtures go through the contract owner. Each worktree has a distinct disposable app database, key file and upload root. Do not share a local SQLite file or credentials between agents.
- Each PR reports changed paths, tests, migration/deployment effects and outstanding assumptions. The integration owner reruns the relevant combined tests after merge, not every unrelated suite in every branch.

## Wave A — independent safety foundations

Start B01 first to establish checks; then the following work can proceed concurrently.

| Agent/worktree | Tasks and exclusive files | Coordination / merge gate |
| --- | --- | --- |
| A: access gate | B02; new `core/authz.py`, login templates, both apps' `views.py`/`urls.py`, access tests | Integration owner handles project settings/root URL registration. Own these route files until complete |
| B: migration preservation | B03; `document_extraction/migrations/`, new migration tests and migration recovery docs | No route/model edits. Establish whether old migration is deployed before choosing patch strategy |
| C: provider safety | B08 contract/adapter work; `document_extraction/services/llm.py`, `services/images.py`, provider test module | Policy integration waits for B05; coordinate safe error contract with later worker owner. No `uploads.py`/`util.py` edits in this wave |
| D: intake limits | B07 decoder/storage helpers and tests; `document_extraction/services/storage.py`, `utils/file_types.py`, `forms.py`, new upload-validation tests | Access owner owns `views.py`; stage any wiring request as a small patch after B02. Do not edit existing `test_uploads.py` concurrently |

## Wave B — ownership and safe source access

B04 then B05 are coordinated changes across existing models/services; assign a single owner and do not overlap them with B10 migrations. After ownership contract merges:

| Agent/worktree | Exclusive ownership | Can overlap safely |
| --- | --- | --- |
| E: source boundary (B06) | `db_extraction/forms.py`, `services/postgres.py`, source-revision models/migrations, source-policy tests | Document evidence and job helper work; source migration numbers remain reserved to E |
| F: job infrastructure (B09 first PR) | New job module/models/management command/tests | No existing document/source service rewiring until the lease contract merges |
| G: deployment scaffold (B27 preparation) | New `deploy/` configuration and operator notes | No requirements/settings edits without integration owner; final runtime wiring waits for B09 |

B09 route/service wiring follows its infrastructure PR and source/evidence boundaries; reserve `document_extraction/services/uploads.py`, `util.py`, `views.py`, `db_extraction/services/extraction.py`, job UI and migration files for that owner during the switch. B10 then owns document models/migrations, records/original services and revision UI. This sequencing prevents simultaneous rewrites of the upload pipeline.

## Wave C — build import and document branches

After B11 canonical AP and B12 mapping contracts merge:

| Agent/worktree | Tasks and exclusive files | Dependency/coordination |
| --- | --- | --- |
| H: importer | B14; new `db_extraction/services/imports.py`, import tests/models/migrations | Mapping compiler contract frozen; no mapping UI edits |
| I: mapping UI | B13; mapping-specific views/forms/templates/tests | Reuse approved compiler; integration owner inserts routes, migration owner handles any schema change |
| J: normalization | B15; new `core/normalization/` and golden tests | Publish versioned interfaces before H/K consumes them; no direct AP schema changes |
| K: page OCR and structured extraction | B16 then B17; document page/parser/structured services, field-edit templates/tests | Own document migrations for this wave. Coordinate accepted canonical field contract with B11/B15 |

Import and document extraction can be developed against synthetic contract fixtures before the real VANS V2 mapping is available. Do not fake completion of source-specific mapping from those fixtures.

## Wave D — reconciliation and review

Merge B19 finding/evidence schema first; merge B18 links before rule implementation. Then:

| Agent/worktree | Tasks and exclusive files | Merge gate |
| --- | --- | --- |
| L: header rules | B20; `reconciliation/rules/headers.py` and its tests | Pure-rule input/output schema frozen |
| M: review service | B23; `reconciliation/services/reviews.py` and transition/role tests | Findings/review models owned by B19 owner; schema requests queued |
| N: report service | B25 backend preparation; `reconciliation/reports/` and manifest tests | Work against synthetic fixed contracts; final integration waits for findings/UI |
| O: line rules | B21 after B20; allocation service, `rules/lines.py` and conservation tests | Allocation migration belongs to one owner; no concurrent B22 edits to this module |

B22 owns `rules/missing.py`/`rules/duplicates.py` after completeness/allocation semantics settle. B24 owns reconciliation views/templates/JS; other agents supply service APIs, not edits to those files. B26 QA owns new corpus/E2E files and raises failures to owners instead of rewriting production code. B28 restore/retention follows final evidence/report contracts.

## AR wave

B29 schema then B30 source mapping then B31 AR rules/UX/validation. Reuse stable shared services, but assign one owner to any shared-rule change and rerun AP golden cases. Do not parallelize AP and AR schema design before common identity/UOM/provenance decisions are stable.

## Suggested branch names

`feat/ci-postgres-baseline`, `fix/workspace-access`, `fix/preserve-text-evidence`, `feat/org-scope`, `fix/source-boundary`, `feat/extraction-jobs`, `feat/evidence-revisions`, `feat/ap-mapping`, `feat/ap-import`, `feat/pdf-page-ocr`, `feat/ap-rules`. Creating these worktrees does not authorize production connections, paid OCR use or deployment; tests remain disposable and synthetic.
