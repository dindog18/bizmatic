# Bizmatic MVP audit and development roadmap

Audit date: **28 October 2026 (Asia/Manila)**. Code baseline: [`f8c1bec`](https://github.com/dindog18/bizmatic/tree/f8c1bec08a22ac27cd77b7349f85368983fc1092), repository default branch `main` at inspection.

**Verdict: useful extraction workspaces; not yet an accounting audit MVP.** The code can store documents, extract text or image Markdown, inspect PostgreSQL schema metadata, and let people edit/review extraction results. It cannot yet import ERP business rows, map them to AP/AR, reconcile PO/DR/SI headers or lines, or issue traceable audit findings/reports. Do not interpret a green test suite or a document's “approved” label as accounting assurance.

The narrowest useful delivery is a **single-organization AP pilot** covering company purchase orders, supplier delivery receipts and supplier sales invoices for one bounded VANS V2 period. AR remains an explicit later slice, not silently included in AP completion. All ERP access stays read-only. Bizmatic's own database holds imports, evidence, findings and review decisions; no ERP write-back is proposed.

## Planning documents

| Document | Purpose |
| --- | --- |
| [MVP gap analysis](mvp-gap-analysis.md) | Actual implementation, ten-step workflow, engineering issues and business impacts |
| [Prioritized backlog](prioritized-backlog.md) | 31 small-PR tasks with dependencies, acceptance, tests and definition of done |
| [Architecture overview](architecture-overview.md) | Current boundaries, proposed models, mapping and accounting semantics |
| [Data flow](data-flow.md) | Current and proposed flows, trust boundaries and failure states |
| [Testing strategy](testing-strategy.md) | Verified baseline, missing layers, accounting fixtures and release gates |
| [Security findings](security-findings.md) | Evidence, exploit prerequisites, safeguards and remediation |
| [First 10 tasks](first-10-tasks.md) | Initial reviewable PR sequence and measurable outcomes |
| [Parallel development](parallel-development.md) | Agent/worktree file ownership and merge coordination |
| [Inspection evidence](inspection-evidence.md) | Scope, commands, results, synthetic probes and limits |

## Decision gates

1. **Safe development:** CI exercises both active apps; access restrictions, tenant scoping, source connection policy and migration preservation are in place. Continue using synthetic data.
2. **AP vertical slice:** versioned mappings and imports plus reviewed structured document fields feed deterministic reconciliation. Every finding identifies the source row and document revision that supports it.
3. **Pilot release:** known-error corpus passes; missing/incomplete data is visible; reviewers can investigate, confirm or dismiss findings; a frozen report includes coverage and unresolved items. Recovery, backups, TLS and operational runbooks are verified.
4. **AR completion:** customer PO → company DR → company SI is independently mapped and tested. AP success does not prove AR correctness.

## Verified baseline

- Pinned root requirements installed on Python 3.14.8; dependency compatibility check passed.
- Django system check and migration drift check passed for the installed apps.
- **65 tests passed:** 47 document tests and 18 database tests, against an isolated in-memory SQLite database with mocked external services.
- `check --deploy` failed under repository defaults: one email-backend error and five security warnings. This does not establish the configuration of any deployed server.
- Three synthetic probes confirmed: an empty PDF becomes “completed” with only `## Page 1`; an anonymous client can download an original; a failed document with no usable extraction can be approved.

No live ERP, real customer documents or paid provider calls were used. Only planning documentation changes belong to this audit. PostgreSQL integration, browser execution, production configuration and actual VANS V2 mappings remain unverified; see the evidence record.
