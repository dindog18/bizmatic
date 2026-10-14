# Document workspace

The Django views query `Document`, `Batch`, `DocExtractionLog`, and
`LLMExtractionLog`. The application does not seed demo records. No application
records were seeded or modified during this integration.

## Behavior

- Document search matches file names (case-insensitive) or an exact document
  number, optionally prefixed with `#`.
- GET filters combine document type, batch (including unassigned), processing
  status, and review status. Apply filters submits the form; Reset clears it.
- Document and batch lists paginate at 25 records. Pagination preserves filters.
  Summary counts reflect all matching documents, including other pages.
- Batch counts and progress are derived from related documents in SQL.
- Detail pages return 404 for missing records. Extraction routes check both the
  document ID and log ID, preventing a log appearing under the wrong document.
- Text and LLM attempts are ordered by creation time, with primary key as a
  tie-breaker. The saved `user_selected_accurate` flag is independent of ordering.
- Empty databases and empty search results show explicit empty states.
- Markdown results render without embedded HTML or remote images.

GET/HEAD pages read saved records. The upload page supports file selection,
removal and drag-and-drop, and submits multipart files with a CSRF token to
`POST /documents/upload/`. It disables duplicate submission while extraction is
running, displays validation errors, and redirects to the saved batch on success.
OCR prompts request Markdown headings, lists and tables; Mistral OCR already
returns Markdown.

Document **Re-Run** posts to `/documents/<document_no>/rerun/`; **Re-Run batch**
posts to `/batches/<batch_no>/rerun/` and processes every document, including those
outside the displayed page. Both reuse the upload extraction flow, the saved
originals, current `.env` providers, concurrency and timeout settings. They keep
the existing documents, batches and historical logs, append new extraction attempts,
and reset review to pending. Previous accuracy selections stay on their original logs.
Buttons show “Re-running…” during the request. Missing originals and overlapping
processing are rejected before any attempts are created. Provider failures return
an error page with saved results retained, as in the upload service.

## Document review

- `/documents/<document_no>/` includes text and LLM extraction history. Empty
  extraction sections are hidden. The former `/logs/` route has been removed.
- Text and LLM result pages offer rendered and raw Markdown, original-file comparison,
  `.md` downloads and an `/edit/` subroute that saves Markdown through POST.
- The original loads automatically from the saved `Document.storage_path` through
  the read-only `/documents/<document_no>/original/` endpoint. There is no file
  chooser or additional upload. Missing files show an unavailable message.
- The endpoint looks up the document ID; it does not accept a browser-supplied
  filesystem path. `?download=1` downloads the saved original.
- Images use the browser image viewer; PDF.js provides PDF page navigation. TXT/CSV show text and tables; DOCX
  shows paragraphs/headings/tables; XLSX shows worksheets and cached cell values.
  Office previews do not reproduce full formatting, images or charts. Legacy
  DOC/XLS and unsupported browser image formats offer an original-file download.
- Bundled PDF.js, JSZip and Marked run locally. Client-rendered Markdown is rebuilt from
  an allowed set of elements and safe links; embedded HTML and images are disabled.

## Document CRUD

- `/documents/<document_no>/review/` accepts POST to approve, reject or reset review.
- Each text/LLM log has a POST `/accuracy/` route. Accuracy is independent for each
  log, matching the model's boolean field; marking an empty extraction is rejected.
- Text and LLM `/edit/` forms save their Markdown. Provider metadata, token counts,
  error details and run status are preserved. Changed text clears that log's accuracy
  and resets document review to pending. Revision tokens reject stale edits with 409.
- `/documents/<document_no>/edit/` edits file name, document type and batch membership.
  The file extension is preserved; storage path, MIME type and processing status
  remain system-managed. This changes metadata, not the file's physical location.
- `/documents/<document_no>/docextract/new/` creates a manual text extraction.
  Provider-generated LLM records continue to come from the upload/OCR process.
- Document and text/LLM log `/delete/` pages require a confirmation POST. Deleting
  a document cascades to its logs. Files on disk and batches are retained.
- Review returns to pending when metadata, content, accuracy or extraction history
  changes. Writes use transactions and document row locks; GET/HEAD never mutate.
- Writes to queued/processing documents return 409 until extraction finishes, so
  upload callbacks cannot overwrite edits or lose their document/log records.
- All POST forms include CSRF protection. Log routes validate both document and log
  IDs. Validation errors stay visible; successful writes show a confirmation message.
- HTTP handlers stay in `views.py`; shared form handling and database writes live
  in `services/management.py` and `services/records.py`.

## Run and verify

From the repository root:

```sh
.venv/bin/python bizmatic_django/manage.py runserver
.venv/bin/python bizmatic_django/manage.py check
.venv/bin/python bizmatic_django/manage.py test document_extraction
```

Open `http://127.0.0.1:8000/documents/`. `manage.py` defaults `DJANGO_DEBUG=true`
only for runserver so local Falcon assets load, unless explicitly overridden.
Install `requirements.txt` when setting up another environment.

Tests create fixtures only in Django's separate test database, which is destroyed
at the end. They cover database-backed rendering, search/filter combinations,
pagination, batch membership/counts, empty states, extraction ownership, Markdown,
and HTTP method restrictions. A query guard rejects non-SELECT SQL during requests.

Models and migrations must be in sync before using the workspace. Uploads save
new batches, documents and extraction logs; validation uses isolated test data.
