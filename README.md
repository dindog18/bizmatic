# Bizmatic

A Django workspace for browsing documents, batches, and extraction history,
with Python services for local file storage, document text extraction, and
image OCR through configurable LLM providers.

## Current functionality

- Database-backed document and batch pages with search, filters, and pagination.
- Document details, text extraction results, and per-provider LLM attempt history.
- Markdown result rendering with embedded HTML and remote images disabled.
- Extraction services for text-based PDFs, DOCX, Excel, TXT, and CSV.
- Image extraction adapters for Ollama, OpenAI, Anthropic, Google, Mistral,
  Alibaba, and DeepSeek. Available capabilities depend on the configured model.

The application pages currently accept GET/HEAD only. Uploading, starting or
rerunning extraction, changing review status, and original-file downloads are
not wired to backend actions. Services can be invoked from Python, but browsing
the UI does not trigger them. See [frontend behavior](bizmatic_django/document_extraction/FRONTEND.md).

## Local setup

Use Python 3.14 and the pinned packages in `requirements.txt`. Commands below run
from the repository root in Bash or Zsh on macOS/Linux.

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For a new checkout, copy the example configuration (keep any existing `.env`):

```sh
cp bizmatic_django/.env.example bizmatic_django/.env
```

Edit `bizmatic_django/.env` and replace `DJANGO_SECRET_KEY`. Generate a value with:

```sh
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Quote the generated value in `.env`, for example `DJANGO_SECRET_KEY='your-value'`.
The example uses SQLite, enables local debug mode, and puts service uploads in
`./storage_file` relative to the working directory. Choose an absolute storage
path if the app will be started from different directories.

The project loads `bizmatic_django/.env` automatically. Start Django with:

```sh
python bizmatic_django/manage.py migrate
python bizmatic_django/manage.py runserver
```

Open [Documents](http://127.0.0.1:8000/documents/) or
[Batches](http://127.0.0.1:8000/batches/). A fresh database shows empty states;
setup does not create sample documents. Restart the server after configuration
changes. `migrate` creates or updates tables in the configured database; it does
not create the PostgreSQL database itself or copy records from an old database.

## Configuration

The complete variable list is in [`.env.example`](bizmatic_django/.env.example).

| Variables | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_TIME_ZONE` | Django runtime settings |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Database connection; SQLite is the default |
| `LOCAL_FILE_STORAGE_PATH` | Directory used by the upload storage service |
| `DOC_EXTRACTION_LLM_PROVIDER` | One provider or a comma-separated provider list |
| `DOC_EXTRACTION_MAX_CONCURRENCY` | Positive concurrency limit, default `5` |
| `DOC_EXTRACTION_LLM_TIMEOUT_SECONDS` | Positive HTTP timeout in seconds, default `120` |
| `DOC_EXTRACTION_<PROVIDER>_*` | Model, API key, and optional endpoint settings |
| `RECONCILIATION_PRICE_TOLERANCE` | Allowed monetary rounding difference per matched line, default `0.01` |

Django commands, ASGI/WSGI startup, and extraction services share the same
`python-dotenv` loader. Its file path is resolved from the project location,
independent of the working directory. Existing process variables take precedence
over `.env`; this includes exports in a terminal and PyCharm run configuration
variables. If an old database setting is exported, unset it or update it before
running a command. Changes to `.env` apply to new processes; restart the server.

No provider credentials are needed to browse the pages or run the existing
tests. To invoke image extraction, select a provider, configure its credentials
where required, and choose a model that supports the input. The example selects
Ollama; start its server and install the configured model before invoking it.
Provider failures propagate to the caller.

PostgreSQL configuration is included as a commented alternative in the example.
To use it, provision a database and set the `DB_*` variables in `.env` before
migrating. `psycopg[binary]` is included in `requirements.txt`. CI uses SQLite.
From the directory containing `manage.py`, inspect the selected target without
printing its user or password:

```sh
python manage.py shell -c 'from django.conf import settings; db = settings.DATABASES["default"]; print({key: db.get(key) for key in ("ENGINE", "NAME", "HOST", "PORT")})'
python manage.py migrate --plan
python manage.py migrate
```

## Project layout

```text
requirements.txt                 Pinned Python dependencies
bizmatic_django/
  manage.py                      Django management entry point
  .env.example                   Shareable configuration template
  bizmatic_django/                Settings and ASGI/WSGI entry points
  document_extraction/
    models.py                    Database models
    migrations/                  Versioned schema changes
    views.py, urls.py            HTTP pages and POST action routes
    schemas/                     Pydantic file metadata and type definitions
    services/                    Storage, document extraction, images, and LLMs
    utils/                       File classification, concurrency, and Markdown
    templates/, static/          Django templates and bundled UI assets
    templatetags/                Safe Markdown presentation
    tests.py, test_environment.py Django view and configuration tests
    util.py                      Compatibility exports
```

The application does not seed demo records. The document workspace shows an
empty state until users upload documents.

## Checks

From an activated environment at the repository root:

```sh
python bizmatic_django/manage.py check
python bizmatic_django/manage.py makemigrations --check --dry-run
python bizmatic_django/manage.py test document_extraction
```

Tests use Django's separate test database. GitHub Actions runs these checks on
Python 3.14 with SQLite. See [CONTRIBUTING.md](CONTRIBUTING.md) for change guidance.

## Operational notes

- Legacy `.doc` files must be converted to `.docx`. Scanned PDFs need an OCR
  workflow; the PDF text extractor does not perform OCR.
- CSV/Excel Markdown rendering needs `tabulate`; Excel readers also use
  `openpyxl` and `xlrd`. All three are included in `requirements.txt`.
- `.env`, virtual environments, local SQLite files, uploads, caches, IDE
  settings, and collected static files are ignored. Custom storage directories
  inside the checkout must also be ignored before adding files to Git.
- These pages currently have no application-level login requirement. Hosting
  publicly requires access control and deployment configuration. Set a unique
  secret, disable debug mode, and configure static-file serving for deployment.
- No project license has been selected. Bundled Falcon and vendor assets have
  their own licensing terms; preserve their existing notices.

## Database extraction

The PostgreSQL metadata workspace opens directly at `/databases/` without a
login or admin account. It supports connection verification, encrypted credentials, schema
snapshots, metadata browsing, and local connection/history deletion. See the
[database module setup and workflow](bizmatic_django/db_extraction/README.md)
for key provisioning, permissions, dependencies, and deployment instructions.

## Accounting reconciliation MVP

Every AP and AR model inherits directly from Django's `models.Model`, with its
fields declared in the app's `models.py`. Model comments explain each record's
purpose. Each app's `services.py` contains plain functions for validation,
matching, and settlement; `signals.py` refreshes cases when document membership
changes. Standard `clean()`, `save()`, and `delete()` hooks call these functions.

The AP and AR models provide a reconciliation backend. Create purchase orders,
delivery receipts, and invoices with their line items. Add the documents to a
`Transaction`, then link the lines through `DocumentMatch`. Matching checks party,
currency, quantities, price, tax, and discounts. Receipt lines record actual
received and accepted quantities. The same quantity cannot be matched twice.
Cases automatically track pending, partial, matched, or exception status and
their discrepancy amount when documents or matches change.

Record payments and allocate cash, withholding tax, and discounts to invoices
through `PaymentAllocation`. Cleared payments reduce the outstanding invoice
balance; reversing a payment removes it from settlement. Payments can be
recorded and cleared independently of matching. Allocations cannot exceed the
payment's available amounts or the invoice total.

`source_document` links to the uploaded file, and the selected extraction log
identifies the text used to populate a record. Database provenance uses
`source_database`, `source_table`, and `source_record_key`; these identify the
external record and prevent duplicate imports. Database Extraction currently
stores schema metadata only, so it does not import business rows.
`RECONCILIATION_PRICE_TOLERANCE` defaults to `0.01` in the transaction currency.
Quantity differences prevent a complete match.
