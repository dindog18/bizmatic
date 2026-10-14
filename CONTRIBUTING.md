# Contributing

Follow the [README](README.md) to create a Python 3.14 environment and configure
the application. Use a local development database and synthetic documents.

## Making changes

- Keep business logic in `document_extraction/services`, Pydantic definitions in
  `schemas`, and shared helpers in `utils`.
- Preserve explanatory comments and update them when behavior changes.
- Keep existing imports through `util.py` working when moving public functions.
- Keep database migrations with model changes. Generate and inspect migrations
  with `python bizmatic_django/manage.py makemigrations`.
- Application views currently accept GET/HEAD only. Changes that introduce
  writes, uploads, or provider calls should describe the new behavior explicitly.
- Update the README and `.env.example` when configuration or setup changes.
- Preserve vendor files and their notices when changing frontend assets.

## Before opening a pull request

```sh
python bizmatic_django/manage.py check
python bizmatic_django/manage.py makemigrations --check --dry-run
python bizmatic_django/manage.py test document_extraction
git diff --check
git status --short
```

Add regression coverage when changing behavior. Tests should use temporary files,
Django's test database, and mocked provider responses instead of live paid APIs.

Review the files you stage. Never include credentials, local databases, real
customer documents, or extracted customer content in commits, fixtures, screenshots,
or issue reports. Commit `.env.example` with placeholders; keep `.env` local.

Describe the problem, resulting behavior, and checks performed in the pull
request. Mention migrations, new dependencies, and remaining limitations.
