# Document routing

Routing reads saved extraction text, evaluates active human-configured rules with
one LLM, and saves zero, one, or multiple `DocumentRoute` decisions per attempt.
Approving an AP/AR destination invokes its accounting extraction using a submitted
configuration. The exact source is retained in `route.routing_log.input_text`.
`services/handoff.py` saves per-route processing status, errors, and completion;
completed routes are not processed twice. See the [accounting guide](../accounts_receivable/README.md).

## Run

1. Apply schema changes with `python manage.py migrate router`.
2. Set the router section in `.env` and restart Django.
3. Add destinations at `/router/destinations/`. Choose AP or AR, then select one of its supported extraction targets.
4. Add active rules explaining when each destination applies and when to exclude it.
5. Use Route document, Route selected, or Route batch in the document workspace.
6. Review the saved destinations and the LLM attempt log in `/router/`.

Source documents must have successful nonempty extracted text and must not be
currently extracting. The most recently saved extraction marked accurate is
preferred; otherwise the most recently saved usable extraction is selected.
Alternate OCR outputs are never concatenated. Input text is never truncated.

Pending and rejected source reviews require the explicit second confirmation.
The server checks saved reviews and revisions again, including every document in
a batch. A changed selection or review returns a fresh confirmation without
starting any calls. Routing does not change the source review or processing state.

## Files

- `models.py`: destinations, rules, LLM attempts, and independent destination reviews.
- `forms.py`: module and target choice validation, including installed model checks.
- `services/catalog.py`: the AP/AR extraction targets shared by the selectors and server validation.
- `schemas/routing.py`: browser execution request and LLM JSON response validation.
- `services/execution.py`: source selection, snapshots, concurrency, and saved results.
- `services/llm.py`: router settings, prompt, native provider payloads, and response parsing.
- `services/configuration.py`: configuration writes and revision checks.
- `services/records.py`: route review, manual destinations, and accuracy feedback.
- `services/handoff.py`: approval-to-accounting execution and explicit failed retries.
- `services/pages.py`: database reads and the JSON used by the existing screens.
- `views.py`, `urls.py`: GET screens and CSRF-protected POST handlers.
- `static/router/`: configuration, review, and history interactions; no browser fixtures.
- `document_extraction/static/document_extraction/routing.js`: execution confirmations.

The shared transport is `document_extraction/services/llm.py`. Router overrides
use the `ROUTER_` environment prefix and the same provider sections as document
extraction. `ROUTER_LLM_PROVIDER` selects one provider, and the corresponding
`ROUTER_OPENAI_MODEL`, `ROUTER_ANTHROPIC_MODEL`, `ROUTER_GOOGLE_MODEL`,
`ROUTER_OLLAMA_MODEL`, `ROUTER_ALIBABA_MODEL`, or `ROUTER_DEEPSEEK_MODEL`
selects its model. Blank credentials and API URLs reuse the
corresponding `DOC_EXTRACTION_` values. Prompts, input text, rules, native request
and response payloads, tokens, timing, source extraction IDs, and any source-review
override are stored in `LLMRoutingLog`. API credentials stay in the HTTP headers.

Like document extraction, execution runs within the triggering HTTP request with
bounded asynchronous concurrency. Configure the server/proxy request timeout for
the chosen batch size and provider latency. Each document has a separate attempt,
and failures leave successful sibling results and previous attempts intact.
Request IDs make retries idempotent; a database constraint prevents overlapping
active attempts for the same source document. A terminated worker can leave an
active attempt requiring an administrator to mark it failed before retrying.

LLM output is accepted only when its complete JSON validates, each destination is
in the rule snapshot, and IDs are unique. No match is a completed attempt with no
routes. Malformed output, truncation, and provider failures are saved as failed
attempts with no partial route assignments.

Destination reviews start pending. Stale source documents and superseded attempts
cannot receive new review decisions or manual destinations. Module/model identities
with routing history cannot be retargeted; create another destination instead.

Queue and LLM list screens show the latest 500 records, with client pagination and
filters. A source document's Routing history link provides its complete attempts.
Tests use a disposable database and mocked LLM calls; no test data is seeded into
the normal application database.

Destination choices cover Supplier/Customer, purchase orders, delivery receipts,
sales invoices, and payments. Changing the module clears the target selection.
Existing destinations outside the current catalog retain their saved identity
when edited; add new supported modules in `services/catalog.py` as they become ready.
