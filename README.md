# Bizmatic

Bizmatic is a Django workspace for extracting business documents, preparing accounting data, and reconciling accounts payable and receivable. It brings document review, PostgreSQL source configuration, and accounting workflows into one application.

> **Project status:** Bizmatic currently runs provider calls and database migrations within web requests. Its workspaces do not provide application-level authentication or organization isolation; restrict access at the hosting layer before making an instance available to others. No project-wide license has been selected. Bundled third-party assets retain their own license terms.

## Features

- **Document operations:** upload and organize documents and batches; extract text from supported files; review, edit, and route extracted results. Image and LLM extraction depend on the configured provider and model.
- **Accounts payable and receivable:** manage suppliers or customers, orders, delivery receipts, invoices, payments, aging, and reconciliation.
- **Database extraction:** connect to PostgreSQL, inspect versioned schema snapshots, and build accounting datasets using a table preview, joins, JSON expansion, type conversions, filters, and sorting.
- **Reviewed updates:** match prepared columns to accounting fields, validate a sample, review all matching source records, and explicitly confirm the migration or subsequent data update. Errors prevent the accounting update.
- **Audit context:** retain extraction attempts, configuration revisions, and source identifiers alongside accounting records.

See the [query builder guide](bizmatic_django/accounts_receivable/QUERY_BUILDER.md) for supported transformations and the [migration guide](bizmatic_django/accounts_receivable/DATABASE_MIGRATION.md) for review and update behavior.

## Requirements

- Python 3.14 and the dependencies pinned in the root [`requirements.txt`](requirements.txt).
- SQLite for a local application database, or a provisioned PostgreSQL application database.
- PostgreSQL 14 or newer for external database extraction. Source connection profiles are configured in the application.
- An optional LLM provider and suitable model for provider-dependent extraction, routing, or setup assistance. Local browsing and database query preparation do not require an LLM.

## Start Bizmatic (Docker by default)

```sh
./bizmatic init       # choose your SQLite file, uploads and credential-key folder
# Review .env.docker: server address, provider/model settings and API keys.
./bizmatic start
./bizmatic stop       # retains data and keys
./bizmatic help
```

Docker runs Django/Gunicorn and Nginx with **SQLite by default**. You provide
persistent host paths and runtime settings; no developer secrets or database
are included in the image. Use `./bizmatic start --dev` while editing Python,
templates, JS or CSS, and `./bizmatic update` to rebuild production code without
resetting data. PostgreSQL is an explicit alternative.

See the [running/deployment guide](deploy/README.md) for the command reference,
Ubuntu setup, PATH installation, backups, model configuration and mode switching.
Native Python remains fully supported below; `./bizmatic runserver` is also a
shortcut to the same native development server.

## Native Python setup (without Docker)

Run these commands from the repository root on macOS or Linux:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp bizmatic_django/.env.example bizmatic_django/.env
```

The copy command is for a new checkout. If `bizmatic_django/.env` already exists, keep it and compare its settings with the example instead of overwriting it.

Edit `bizmatic_django/.env` and set a unique `DJANGO_SECRET_KEY`. For example, generate a key with:

```sh
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Quote the value in `.env`. The example uses SQLite, enables debug mode for local development, and stores uploads in `./storage_file` relative to the process working directory. Use an absolute `LOCAL_FILE_STORAGE_PATH` if you start the application from different directories.

If you plan to save external database connections, provision the credential encryption key before creating connection profiles. The command preserves an existing key:

```sh
python bizmatic_django/manage.py init_db_credential_key
```

Apply the application migrations and start the development server:

```sh
python bizmatic_django/manage.py migrate
python bizmatic_django/manage.py runserver
```

Open [Documents](http://127.0.0.1:8000/documents/), [Accounts payable](http://127.0.0.1:8000/accounts-payable/), [Accounts receivable](http://127.0.0.1:8000/accounts-receivable/), or [Database connections](http://127.0.0.1:8000/databases/). A fresh installation starts without seeded business records. `migrate` updates tables in the configured application database; it does not create a PostgreSQL database or transfer existing records.

## Environment configuration

The application loads **`bizmatic_django/.env`** automatically, regardless of the working directory. Process environment variables take precedence. Restart the process after editing the file.

| File or setting | Purpose |
| --- | --- |
| [`bizmatic_django/.env.example`](bizmatic_django/.env.example) | Tracked template with placeholders, defaults, and optional provider settings. It is safe to share. |
| `bizmatic_django/.env` | Your local runtime configuration and secrets. It is ignored by Git and must not be committed. |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_TIME_ZONE` | Django runtime settings. Use a unique secret and disable debug mode outside local development. |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | The **application** database. The example defaults to SQLite; PostgreSQL values are documented in the template. |
| `LOCAL_FILE_STORAGE_PATH` | Directory for uploaded files. Store it outside the repository or ensure it is ignored. |
| `DOC_EXTRACTION_*`, `ROUTER_*`, `ACCOUNTS_PAYABLE_*`, `ACCOUNTS_RECEIVABLE_*`, `CONFIG_ASSISTANT_*` | Provider, model, endpoint, timeout, and request limits for each workflow. Blank module-specific keys and endpoints can fall back to document-extraction settings. |
| `RECONCILIATION_PRICE_TOLERANCE` | Allowed monetary difference per matched line; defaults to `0.01`. |

Source PostgreSQL credentials are entered in **Database connections**, separately from the application database settings. Saved passwords are encrypted with a key stored by default at `~/.config/bizmatic/db-extraction.key`. Keep that key outside Git, make it available to all application workers, and back it up separately from the application database. See the [database extraction guide](bizmatic_django/db_extraction/README.md) for permissions, encryption, and schema discovery.

## PDF previews behind Nginx

PDF previews load the bundled PDF.js JavaScript modules from
`/static/document_extraction/vendors/pdfjs/`. Both `pdf.min.mjs` and
`pdf.worker.min.mjs` must be served with a JavaScript MIME type. A response with
`Content-Type: application/octet-stream` causes the browser to reject the module,
even when the original PDF downloads successfully. The page then shows
“Preview unavailable” with a “Failed to fetch dynamically imported module” detail.

On Ubuntu, edit the existing JavaScript entry in `/etc/nginx/mime.types` to
include `mjs`, preserving its other extensions:

```nginx
application/javascript  js mjs;
```

Ensure the Nginx configuration serving `/static/` uses that MIME table, normally
through `include /etc/nginx/mime.types;` in the `http` block. If the static-file
location defines its own `types` block, update its JavaScript entry as well;
that block overrides the inherited table. See the [Nginx types documentation](https://nginx.org/en/docs/http/ngx_http_core_module.html#types).

Validate the configuration before reloading:

```sh
sudo nginx -t && sudo systemctl reload nginx
```

Check the response headers for **both** module URLs on the deployed host. They
should return HTTP 200 with `application/javascript` (or `text/javascript`). Then
hard-refresh the document page to discard cached responses with the old MIME
type. This change does not require a database migration or a Django restart.

## Document extraction limits

PDF and Office extraction reject files larger than 25 MiB. PDF table discovery
allows at most 100 pages, 512 estimated edges per page and 4,096 per document.
The estimate counts individual drawing items and inferred path bounds, including
rectangles and closed paths. Documents beyond these limits fail with a message
to split or simplify the file; text is not silently dropped.

DOCX and ZIP-based Excel packages allow at most 2,048 entries, 16 MiB per
expanded entry and 64 MiB of expanded content in total. Only stored and DEFLATE
members are accepted. Raw compressed streams are checked with bounded output,
actual size, checksum and stream-end validation before opening the Office
parser. This also applies to ZIP-based workbooks named `.xls`.

These checks bound Office package expansion and PDF table-discovery complexity.
They do not isolate native PDF decompression, XML parsing, legacy XLS parsing,
or browser previews. Keep hosting access restrictions and worker resource limits
appropriate for untrusted documents. No database migration is required.

## Setup assistant conversations

AP and AR document and database setup include an advice-only Setup assistant. It uses the current inputs and the saved conversation to answer questions; it cannot edit settings, prompts, extracted text, mappings, or accounting data.

Each signed-in user (or anonymous browser session) has one continuous conversation per workspace, record type, and extraction source, shared across configurations with that selection. Messages are saved immediately, even before the configuration is saved. **Clear chat** deletes that conversation and keeps the setup inputs. There is no conversation list. At 100 messages or the input size limit, clear the chat to continue; older messages are never silently dropped. Provider attempt logs remain available in LLM activity as audit evidence and are not used as conversation context after clearing. Existing configuration-bound assistant messages are retained only as historical data and are not imported into these new conversations.

Apply the included database migration with `python bizmatic_django/manage.py migrate`. No new environment variables or dependencies are required; replies use the existing `CONFIG_ASSISTANT_*` provider settings.

## Database extraction workflow

1. Add and test a PostgreSQL connection, then refresh its schema.
2. In AP or AR extraction setup, choose a source table and prepare the data with ordered transformation steps.
3. Match the final columns to the destination accounting fields. Line-item fields are optional; missing line numbers can be generated.
4. Validate a sample and review the full migration. Confirm only after the review reports no errors.
5. For a saved setup, use **Update data** to review and apply later source changes.

Source previews use read-only transactions. The source database needs the appropriate read privileges; the application database stores the accounting records after confirmation. Full reviews and updates run synchronously, so large datasets may require suitable application and proxy timeouts.

## Project layout

```text
bizmatic_django/
  manage.py                    Django management entry point
  .env.example                 Shareable environment template
  bizmatic_django/             Settings, environment loader, ASGI and WSGI
  document_extraction/         Documents, storage, extraction, and review
  db_extraction/               PostgreSQL connections and schema snapshots
  router/                      Document routing and handoff
  accounts_payable/            Accounts payable models and workflows
  accounts_receivable/         Accounts receivable and shared AP/AR services and UI
requirements.txt               Pinned root dependencies
CONTRIBUTING.md                Development and contribution guidance
```

## Development and documentation

```sh
python bizmatic_django/manage.py check
python bizmatic_django/manage.py makemigrations --check --dry-run
python bizmatic_django/manage.py test document_extraction
```

Tests use a separate Django test database. Consult [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. More detail is available in the [document workspace guide](bizmatic_django/document_extraction/FRONTEND.md), [database extraction guide](bizmatic_django/db_extraction/README.md), [AP/AR guide](bizmatic_django/accounts_receivable/README.md), [query builder guide](bizmatic_django/accounts_receivable/QUERY_BUILDER.md), and [migration guide](bizmatic_django/accounts_receivable/DATABASE_MIGRATION.md).

Text extraction supports text-based PDFs, DOCX, Excel, TXT, and CSV. Scanned PDFs require an OCR workflow; legacy `.doc` files must be converted to `.docx`. Provider and model capabilities vary, and provider calls may incur charges. Static vendor assets and fonts include their own notices in the repository.
