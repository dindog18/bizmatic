# Inspection evidence and limits

## Baseline and method

- Repository: [dindog18/bizmatic](https://github.com/dindog18/bizmatic).
- Inspected default-branch commit: `f8c1bec08a22ac27cd77b7349f85368983fc1092` (`Integrate database workspace into Django navigation`). Audit date: 28 October 2026, Asia/Manila.
- Repository inventory: **330 tracked files**, **76 Python files / 4,932 Python lines**, **27 templates**. Review covered project configuration, app registration/routes, models/migrations, service logic, credentials, forms, custom frontend JavaScript, templates, tests, dependencies, CI and project docs.
- Vendor PDF.js/Marked/JSZip/Falcon assets, fonts and binary resources were inventoried; they were not manually audited line by line or checked against a vulnerability feed. Custom integration code was inspected. No formal SAST/dependency-vulnerability scan was run.
- No `AGENTS.md` was found in the checkout or checked parent instruction locations. Existing `CONTRIBUTING.md` was read; its GET/HEAD-only claim was checked against actual routes rather than assumed current.
- Only `document_extraction` and `db_extraction` are installed business apps. AP/AR files exist but are placeholders; there is no reconciliation app or shared accounting schema in tracked source.
- GitHub workflow lookup for this commit returned an empty run list through the connector. This means no run was returned, not proof that workflows were never executed. CI configuration was inspected locally and its commands reproduced/expanded below.

## Safety of execution

The checkout had no real `.env` or database files. Commands explicitly selected SQLite `:memory:` and synthetic secrets/test hosts. Dependencies were installed into an isolated scratch virtual environment using Python 3.14.8. Existing tests use temporary storage and mocked external catalog/provider calls. Additional probes patched `psycopg.connect` and provider HTTP dispatch to fail if invoked. No live ERP host, source credentials, customer document, production migration or paid OCR API was used.

The existing test suite creates and tears down its own disposable test schema; its credential-migration test performs DDL only on that isolated schema. No destructive operation was performed on a user or production database. Synthetic probe setup applied migrations only to a fresh in-memory application database. Application functionality was not edited.

## Commands and observed outcomes

Commands below are relative to the repository root with the pinned environment activated. Test-only secret values are intentionally omitted from documentation; none are needed to reproduce content fixtures.

```sh
uv venv --python 3.14 /path/to/isolated-audit-venv
uv pip install --python /path/to/isolated-audit-venv/bin/python -r requirements.txt
uv pip check --python /path/to/isolated-audit-venv/bin/python
```

Install succeeded with **57 packages**; compatibility check passed. The interpreter was Python 3.14.8, matching the repository's 3.14 minor-version requirement. Root requirements include Django 6.1.2.

```sh
export DB_ENGINE=django.db.backends.sqlite3
export DB_NAME=:memory:
export DJANGO_DEBUG=False
export DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,testserver
python bizmatic_django/manage.py check
python bizmatic_django/manage.py makemigrations --check --dry-run
python bizmatic_django/manage.py test document_extraction db_extraction --noinput --verbosity 2
```

Observed: system check reported no issues; no migration drift detected; **65 tests ran in 4.137 seconds and passed**. AP/AR are not installed, so “no changes detected” does not establish AP/AR schema completeness. Tests: document 47, database 18. No skipped tests were reported. Full local logs were inspected; only synthetic test data was present.

```sh
python bizmatic_django/manage.py check --deploy
```

Executed with explicit in-memory DB, `DEBUG=False`, local/test hosts, and repository-default fallback secret. Exit code 1; **one error and five warnings**:

| Check | Observed result |
| --- | --- |
| `mail.E001` | Default MAILERS entry uses development-only console backend |
| `security.W004` | HSTS seconds not configured |
| `security.W008` | SSL redirect not enabled |
| `security.W009` | Repository fallback secret is unsuitable |
| `security.W012` | Session cookie not secure-only |
| `security.W016` | CSRF cookie not secure-only |

These are repository-default results, not an inspection of production settings or proxy protections. Do not weaken checks to make them green; establish the deployment policy in B27.

## Additional synthetic probes

All probes ran in a fresh SQLite in-memory application database with temporary files. No test code was added to the application in this documentation-only task.

| Probe | Setup | Observed output | Meaning |
| --- | --- | --- | --- |
| Blank PDF upload | Generate one empty page with PyMuPDF; POST as PDF without authentication | HTTP 302; Document `processing_status=completed`; text log exactly `## Page 1` | Page headings alone are accepted as extracted content; this proves missing empty-text guard, not OCR quality |
| Anonymous original | GET original for that synthetic PDF | HTTP 200; response bytes match uploaded bytes | Workspace has no application login requirement for originals |
| Approve failed/empty document | Set synthetic document processing status failed; clear text and accuracy; POST review `approved` | HTTP 302; processing remains `failed`, review becomes `approved` | Review eligibility is not tied to usable extraction evidence |

Static migration evidence: `document_extraction/migrations/0002_llmextractionlog_user_selected_accurate_and_more.py` uses `CreateModel(DocExtractionLog)` followed by `DeleteModel(TextExtractionLog)` with no rename or data-copy operation. The populated upgrade path was **not** exercised by this audit; the data-loss risk follows directly from the migration operations. B03 requests a disposable regression test and safe migration-state strategy. No claim is made about whether any deployment had populated old text logs.

## What was not verified

- Actual VANS V2 schema, PostgreSQL version, row volumes, keys, business rules, data quality or source permissions. No mapping can be declared production-ready from this repository alone.
- Live PostgreSQL SQL execution, TLS, privileges, source catalog compatibility, source load or concurrency semantics. No PostgreSQL server/binary was available in this environment; existing tests mock the source. The README's prior PostgreSQL 17 verification claim is not independently reproduced here.
- Actual OCR/LLM correctness, provider availability or all seven provider contracts. Tests stub OpenAI/Ollama responses; model names in tests are not endorsements or verified deployment choices.
- Browser execution, screenshot/accessibility audit, real frontend rendering at scale, or bundle vulnerability assessment. Template and custom JS review plus Django response tests provide only partial frontend evidence.
- Production app/proxy/server/service configuration, deployed database migration state, backup contents, secret rotation, disaster recovery or resource budgets. README deployment references are not checked-in deployment infrastructure.
- Measured test line/branch coverage or OCR percentage. Passing 65 tests is the exact executed baseline, not a statistical claim about correctness.

## Documentation validation

Before delivery: verify all relative Markdown links, all commit-pinned source paths/line anchors, backlog IDs/dependencies, expected document set and absence of unresolved template markers. Run `git diff --check`, inspect staged filenames and confirm all changes are under `docs/mvp-audit/`. No application re-test is needed solely because Markdown changed after the recorded baseline, unless validation reveals a code change.
