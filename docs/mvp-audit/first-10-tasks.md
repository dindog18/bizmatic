# Proposed first 10 development tasks

These first ten tasks establish a safe foundation. They do **not** complete reconciliation. The remaining AP workflow is B11–B28 in the [full backlog](prioritized-backlog.md); AR is B29–B31. Each linked task contains affected apps, implementation, dependencies, acceptance criteria, tests and definition of done.

| Order | PR-sized result | Why now | Concrete review artifact |
| --- | --- | --- | --- |
| 1. [B01](prioritized-backlog.md#b01) | CI runs both apps and isolated PostgreSQL checks; stale behavior docs corrected | Existing CI omits database tests | CI logs collecting 65 existing tests, plus new PostgreSQL checks |
| 2. [B02](prioritized-backlog.md#b02) | Login and role gates on every existing route | Anonymous access currently includes originals and mutations | Route/role test matrix; login/logout workflow |
| 3. [B03](prioritized-backlog.md#b03) | Safe upgrade/recovery path for old text logs | A historical create/delete migration loses old evidence | Populated synthetic migration rehearsal and recovery instructions |
| 4. [B04](prioritized-backlog.md#b04) | Organization/membership models and explicit ownership backfill | Later source, document and audit data must share a boundary | Reviewed migrations and synthetic two-organization fixtures |
| 5. [B05](prioritized-backlog.md#b05) | Tenant scope throughout routes/services/forms/admin | Login alone would expose every organization | Cross-tenant rejection tests covering originals and source actions |
| 6. [B06](prioritized-backlog.md#b06) | Approved source endpoints, safe credentials/TLS and read-only preflight | Protect ERP boundary before importing rows | Disposable role/TLS tests, no-DML connector assertions and DBA runbook |
| 7. [B07](prioritized-backlog.md#b07) | File/content/resource limits and safe storage boundary | Current intake is unbounded and MIME-driven | Synthetic malformed/over-limit rejection cases with zero provider calls |
| 8. [B08](prioritized-backlog.md#b08) | Provider data-routing policy and sanitized diagnostics | Customer documents must not flow to unspecified vendors | Mock provider tests including fake-secret error redaction |
| 9. [B09](prioritized-backlog.md#b09) | Durable jobs, leases, idempotency and recovery | HTTP-request lifetime cannot be the audit processing lifetime | Worker-kill/retry demonstration with no duplicated logical result |
| 10. [B10](prioritized-backlog.md#b10) | Hashed originals and immutable extraction/correction revisions | Findings will need stable evidence | Before/after revision lineage, protected deletes and invalid approval tests |

## Ready for task 11 when

The two-organization security fixture passes; the source connector is restricted and tested; historical evidence survives the migration path; approved document input runs through recoverable jobs with immutable provenance. Then install the canonical AP model, freeze the mapping contract and develop ERP imports and structured document fields in parallel.

## First vertical-slice demonstration

Use only a synthetic source and documents: PO 10 units, two DRs of 6 and 4, and one SI with a deliberate price difference. Show exact source keys, imported counts/totals, page evidence, Decimal difference, reviewer rationale and frozen report. Re-run the import/extraction, interrupt a worker and retry, and demonstrate that the original report remains unchanged. This is the first useful accounting milestone, not the existence of new model classes alone.
