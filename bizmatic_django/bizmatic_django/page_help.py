"""Component tours. Missing or hidden targets are skipped by help-tour.js."""


def tour(title, *steps):
    return {"title": title, "steps": [dict(zip(("selector", "title", "text"), step)) for step in steps]}


TABLE = ("#page-content table", "Read the records", "Each row is one saved record. Open its link to inspect the details.")
SEARCH = ('#page-content input[type="search"]', "Find a record", "Type a name or reference here to narrow the list.")
SAVE = ('#page-content form button[type="submit"]', "Save your changes", "After checking the fields, use this button to save. This tour does not submit forms.")
NAV = (".finance-nav", "Choose a workspace page", "Use these tabs to move between records, reconciliation, extraction setup and LLM activity.")
GUIDES = {
    "setup": tour("Application setup",
        ("#page-content .alert", "Check what is missing", "Only active modules contribute to this count. Optional secret-storage steps do not block Encoder setup."),
        ("#module-selection", "Activate only the modules you use", "Choose which modules contribute setup reminders for this workspace, then save. Inactive modules remain accessible and existing processing is unchanged."),
        ("#ENCODER", "Set up Encoder", "Enable local access, test an MCP connection, permit tools and add an Encoder routing destination. External execution always needs payload confirmation."),
        ("#DOC_EXTRACTION", "Prepare document extraction", "Configure a document provider before uploading files."),
        ("#ROUTER", "Prepare routing", "Add destinations and active rules that describe which documents belong there."),
        ("#ACCOUNTS_PAYABLE", "Set up Accounts payable", "Submit extraction instructions for the supplier records you need."),
        ("#ACCOUNTS_RECEIVABLE", "Set up Accounts receivable", "Submit extraction instructions for the customer records you need."),
        ("#DB_EXTRACTION", "Optional database setup", "Complete these steps only if you plan to import from PostgreSQL.")),
    "documents": tour("Documents", SEARCH,
        ('#page-content form[method="get"]', "Filter the list", "Choose type, batch, processing or review status, then Apply filters."),
        TABLE,
        ('#page-content table input[type="checkbox"]', "Select documents", "Check the rows you want to route. Open each document first to verify its extracted text."),
        ('[data-routing-trigger="selected"]', "Route your selection", "After selecting reviewed documents, use Route selected. Unapproved reviews require an extra confirmation.")),
    "document": tour("Review a document",
        (".file-preview, .original-preview", "Check the original", "Use this preview as evidence when checking the extracted text."),
        ('[aria-labelledby="information-heading"]', "Read the document status", "Processing tracks extraction. Review shows whether a person approved the text."),
        ("#extraction-results", "Compare the extracted text", "Check references, dates, amounts and items against the original."),
        ('[aria-labelledby="review-heading"]', "Record your review", "Approve correct text or reject it when corrections are needed."),
        ('[data-routing-trigger="document"]', "Send it to routing", "Routing proposes destinations and can start AP/AR extraction automatically. Encoder only creates a draft; external execution requires separate confirmation.")),
    "upload": tour("Upload documents",
        (".upload-zone", "Choose your files", "Drop files here or use the file picker to select documents and images."),
        ("#upload-submit", "Start extraction", "Upload and extract saves the files and starts text extraction. Review the results afterwards.")),
    "batches": tour("Batches", TABLE),
    "batch": tour("Review a batch",
        ('[aria-labelledby="batch-information-heading"]', "Check batch progress", "This summarizes extraction for the upload group. Completed files still need review."), TABLE,
        ('[data-routing-trigger="selected"]', "Route checked files", "Select document rows to enable routing for only those files."),
        ('[data-routing-trigger="batch"]', "Route the entire batch", "Use this after reviewing the batch. Pending or rejected reviews require confirmation."),
        (".rerun-form button", "Extract again if needed", "Re-Run batch creates new extraction attempts using current settings.")),
    "edit_document": tour("Edit document details", ("#page-content form", "Update document information", "Correct the document details here. This does not edit an accounting record."), SAVE),
    "extraction": tour("Extraction results",
        (".extraction-markdown, .markdown-editor, .raw-text", "Check the saved text", "Compare this attempt with the original. Correct errors here if an editor is shown."),
        ("#page-content .metadata", "Inspect the attempt", "These details describe the extraction result and its status."), SAVE),
    "queue": tour("Routing review",
        (".router-metrics", "Read the queue summary", "These counts summarize routing outcomes and reviews needing attention."), SEARCH, TABLE,
        ('.router-heading a', "Start routing from documents", "New routing attempts begin from Documents or Batches. Open a queue row to review proposed destinations.")),
    "route": tour("Review document destinations",
        (".router-route-card, .router-route", "Review a destination", "Check its proposed module, record type and reason against the source text."),
        ('[data-review-form] button[value="approved"]', "Approve only after checking", "Approval records your destination decision. AP/AR extraction may already have run automatically; approval retries it when needed. Encoder approval permits later review and explicit execution, never an automatic MCP call."),
        ('#router-root select', "Choose the extraction profile", "If several profiles match, choose the one appropriate for this document."),
        ("#router-root .card", "Inspect the result", "Review status is your decision; processing status tracks creation of the accounting record. Read any errors before retrying.")),
    "destinations": tour("Routing destinations", SEARCH, TABLE,
        ('[data-action="delete-configuration"]', "Remove unused destinations", "Delete opens a confirmation. Confirmation deletes all associated routing rules and removes this destination from configuration. Past routes and downstream records are retained."),
        ("#router-name", "Name the destination", "Use a label reviewers recognize, such as Supplier invoices."),
        ("#router-module_name", "Select the module", "Choose Accounts payable, Accounts receivable or Encoder."),
        ("#router-target_model", "Select the record type", "Select the record type for this module, or Encoder job to create an encoding draft."),
        ("#router-active", "Enable routing to this destination", "Only active destinations are considered. Add active rules, plus submitted AP/AR extraction profiles or an Encoder MCP connection as appropriate."), SAVE),
    "rules": tour("Routing rules", SEARCH, TABLE,
        ('[data-action="delete-configuration"]', "Delete a rule", "Review the rule name and confirm deletion. Past routing attempts retain their snapshots. Disable a rule instead if you may want to reuse it."),
        ("#router-name", "Name the rule", "Choose a name that explains what this rule recognizes."),
        ("#router-destination", "Choose a destination", "This rule will recommend the selected module and record type."),
        ("#router-encoder-fields", "Choose the Encoder operation", "For an Encoder destination, choose an enabled MCP connection and permitted operation here. Routing builds and validates a draft, using shared AI when values are missing. Resolve remaining issues in Encoder chat and confirm external execution separately."),
        ("#router-instructions", "Explain what should match", "Describe the issuer, recipient and evidence to include. State when this destination should be excluded."),
        ("#router-examples", "Add useful examples", "Give examples of documents that should and should not match."),
        ("#router-active", "Activate the rule", "Only active rules for active destinations are used."), SAVE),
    "routing_logs": tour("Routing history", SEARCH, TABLE,
        ("#router-root pre", "Inspect the attempt", "Compare the saved input and response with the intended routing result.")),
    "database": tour("Database metadata", SEARCH, TABLE,
        ('#page-content a[href$="/new/"]', "Add a connection", "Enter connection details and test them. Test and save verifies the submitted details before storing a connection; then refresh metadata."),
        ('#page-content form[action$="/test/"]', "Test the connection", "This checks access to the external database. It does not import accounting records."),
        ('#page-content form[action$="/refresh/"]', "Refresh the schema", "Create a metadata snapshot, then use its tables in an AP or AR database configuration.")),
    "database_form": tour("Database connection",
        ("#id_name", "Name the connection", "Use a recognizable label for this external database."),
        ("#id_host", "Locate the server", "Enter the PostgreSQL host. Set the port and database name in the fields below."),
        ("#id_username", "Set the database account", "Use the account supplied by your administrator."),
        ("#id_password", "Set its password", "Passwords are stored encrypted. Follow the form's instructions when editing an existing connection."),
        ("#id_ssl_mode", "Choose SSL settings", "Use the SSL mode required by the database server."), SAVE),
    "overview": tour("Overview", NAV,
        ('#page-content select', "Choose a currency", "Compare totals in one currency at a time."),
        (".finance-kpis, .finance-metrics", "Read the balances", "These figures summarize saved accounting records and allocations."), TABLE),
    "parties": tour("Customers and suppliers", SEARCH, TABLE,
        ("#page-content form", "Maintain account details", "Enter an account code and recognizable name. Extraction lookups must match these saved accounts."), SAVE),
    "orders": tour("Purchase orders", SEARCH, TABLE,
        (".finance-meta", "Check the order", "Compare account, dates, amounts and source evidence before reconciliation.")),
    "deliveries": tour("Delivery receipts", SEARCH, TABLE,
        (".finance-meta", "Check the receipt", "Compare references and delivered quantities with the source before matching lines.")),
    "invoices": tour("Invoices", SEARCH, TABLE,
        (".finance-meta", "Check the invoice", "Verify its account, dates, currency and totals. Saved allocations determine the unpaid balance.")),
    "payments": tour("Payments", SEARCH, TABLE,
        ('#page-content a[href$="/allocate/"]', "Allocate a payment", "Open allocation to apply this payment to eligible invoices of the same account and currency.")),
    "allocate": tour("Allocate a payment",
        ("[data-allocation]", "Enter an allocation", "Set how much of this payment to apply to the invoice. Stay within its remaining balance."),
        ("#allocation-summary", "Check the total", "The allocated total must not exceed the payment amount available."), SAVE),
    "reconciliation": tour("Reconciliation", SEARCH, TABLE,
        ("#page-content form", "Build a case", "Choose one account, the currency and related documents, including at least one invoice."), SAVE,
        ('#page-content a[href$="/match/"]', "Match the lines", "Compare order, receipt and invoice lines after saving the case.")),
    "match": tour("Match document lines",
        ("[data-order], [data-receipt], [data-match-invoice]", "Connect related lines", "Select lines describing the same goods across the documents in this case."),
        ("[data-quantity]", "Set the matched quantity", "Enter the quantity being compared. Check differences against the original evidence."), SAVE),
    "aging": tour("Aging report",
        ('#page-content select', "Choose a currency", "Review outstanding balances in the same currency."),
        ("#page-content table", "Read the aging buckets", "Balances are grouped by due date. Open the related account or invoice to investigate.")),
    "configurations": tour("Extraction setup",
        (".config-targets", "Choose a record type", "Select what you want to extract. Counts include drafts, which cannot process records."),
        ("#configuration-list", "Review saved profiles", "Check target, source, scope and status. Only submitted configurations are used for extraction."),
        ('.finance-heading a[href*="configuration/new"]', "Create a configuration", "Set up a document profile for routing or a database profile for importing.")),
    "configuration_form": tour("Configure extraction",
        (".lab-scope", "Choose the record and source", "Choose AP or AR, the record type, and document or database extraction. Each selection keeps its own working configuration."),
        ("#setup-name", "Name the configuration", "Use a name that describes this layout or mapping. Optional scope and formatting settings apply to the selected record."),
        ("#da-source-text", "Choose the extracted text", "Choose a successful document extraction or paste text. Edit it before locking it for annotation."),
        ("#da-annotation-text", "Highlight field values", "Assign highlighted values to the matching field. Colors identify individual fields; required and optional labels remain separate."),
        ("#qb-panel-mapping", "Map database fields", "Choose a table and column for each destination field. Declared relationships connect related tables; review unknown matches manually."),
        ("#qb-panel-filters", "Refine the selected rows", "Choose a table and column for every condition. Combine AND/OR groups and inspect a read-only query test."),
        ("#da-prompt", "Test the extraction prompt", "The configuration assistant generates the prompt from your annotations. Test it against extracted text and compare expected values."),
        ("[data-setup=draft]", "Save unfinished work", "Review and confirm a draft. Drafts remain inactive until they pass a mapping test and are confirmed again."),
        ("[data-da=review], [data-qaction=review-query]", "Confirm the tested setup", "Only a current passing test enables activation. Review the exact configuration and confirm before saving."),
        ("[data-setup=import]", "Import reviewed database records", "After activation, run a bounded import from the saved query. The result lists created records and issues.")),
    "logs": tour("LLM activity", SEARCH, TABLE,
        ("#llm-output", "Inspect the saved output", "Compare the response with the original source and resulting accounting record."),
        ("#llm-accuracy", "Record your accuracy review", "Choose an accuracy assessment only after checking the completed attempt.")),
}


ENCODER_NAV = ('.finance-nav', "Move through Encoder", "Use Document queue, MCP connections and Execution history to prepare and inspect encoding jobs.")
GUIDES.update({
    "encoder_queue": tour("Encoder document queue", ENCODER_NAV,
        ('#status', "Filter processing status", "Jobs arrive only through Router. Filter to find jobs needing review or retry; open a document to continue."),
        TABLE,
        ('a[href="/router/"]', "Review the route first", "Routing creates a draft, never an external write. Approve the current source document and route before confirming an MCP operation.")),
    "encoder_job": tour("Encoder document workspace", ENCODER_NAV,
        ('#reset-workspace', "Start a fresh cycle", "Reset archives the current draft and starts an empty conversation. Previous chats, LLM logs and execution attempts remain available. It never undoes ERP changes; uncertain outcomes still require verification."),
        ('.file-preview', "Compare the original", "Use the existing document preview and extracted text as evidence. Encoder does not perform OCR again."),
        ('[data-routed-operation], [data-operation-form]', "Review the permitted operation", "New routing rules select the MCP connection and operation and prepare the payload automatically. Older drafts still allow a manual selection here. The tool schema supplies required and optional fields."),
        ('form[action$="/payload/"]', "Prepare and validate values", "Correct fields and save to validate. Mappings, defaults and AI suggestions can prepare values; missing required information must be supplied or flagged."),
        ('#encoder-chat', "Troubleshoot with AI", "Chat uses this job's document, schema and errors. Inspect a proposal and apply or reject it separately; AI cannot execute the MCP tool."),
        ('#confirm-execution', "Confirm the exact payload", "Review the payload before checking this box. Only the separate Confirm and execute button calls the tool. Changes invalidate old confirmations."),
        ('#execution-history', "Inspect attempts before retrying", "Timeouts and tool errors may have unknown external outcomes. Verify the ERP result before retrying unless the identical request uses a documented idempotency key.")),
    "encoder_connections": tour("MCP connections", ENCODER_NAV, TABLE,
        ('a[href$="/connections/new/"]', "Add an MCP connection", "Choose STDIO for a local process or Streamable HTTP for an endpoint. Testing discovers tools without calling a business operation.")),
    "encoder_connection_form": tour("Configure an MCP connection", ENCODER_NAV,
        ('#id_name', "Name the server", "Choose a recognizable connection name."),
        ('.encoder-transport', "Choose the transport", "STDIO launches a local server process; Streamable HTTP connects to an HTTP(S) MCP URL. Only the selected type's inputs are used."),
        ('[data-field="command"]', "Set the launch command", "Enter the executable and use one row per argument below. Arguments are literal values, not a shell command."),
        ('[data-field="server_url"]', "Set the endpoint", "Enter the server's MCP endpoint URL, such as https://mcp.example.com/mcp. Existing ERP authentication still applies."),
        ('[data-field="environment"], [data-field="http_headers"]', "Supply secret values", "Use key/value rows. Saved secrets remain hidden; empty rows preserve them only for unchanged connection details. Re-enter or explicitly clear secrets when changing the destination."),
        ('[data-field="environment_passthrough"], [data-field="env_http_headers"]', "Read server environment variables", "Enter environment-variable names available to Django. Missing variables are reported before connecting."),
        ('button[name="intent"][value="test"]', "Test without saving", "Initialize the MCP server and discover its tools. This does not call a business tool or save a connection."),
        ('button[name="intent"][value="save"]', "Test and save", "The submitted settings are retested before saving. Review and permit tools on the saved connection; saving never executes them.")),
    "encoder_connection": tour("Review MCP tools", ENCODER_NAV,
        ('button[value="discover"]', "Refresh discovered tools", "Test this saved connection and read the server's current tool catalog. Changed tools lose their prior approval."),
        ('input[name="approved_tools"]', "Permit intended operations", "Inspect each tool's description and schema before permitting it. Execution still requires a separate confirmed job payload."),
        ('details', "Inspect the input schema", "Required fields, types and nested structures define validation and mapping for each operation.")),
    "encoder_mapping": tour("Reusable Encoder mapping", ENCODER_NAV,
        ('#mappings', "Configure source paths and defaults", "Map tool fields from existing extracted data using source paths, supported transformations and explicit defaults. Missing required business values are never invented."),
        ('#idempotency_field', "Configure idempotency only when documented", "Choose a string parameter only if the server documents it as an idempotency key. Encoder supplies a stable job UUID; the server must enforce deduplication.")),
    "encoder_history": tour("Encoder execution history", ENCODER_NAV, TABLE,
        ('.encoder-json', "Review the submitted data and result", "Each attempt retains its exact payload, tool schema, response, confirmation time and errors. An unknown result must be checked externally before retrying.")),
    "database_runs": tour("Database extraction history", TABLE),
    "database_run": tour("Database extraction run", TABLE, ('#page-content .card', "Read the snapshot outcome", "This is one metadata extraction attempt. Failures do not replace earlier successful snapshots.")),
    "database_table": tour("Database table metadata", TABLE, ('#page-content .card', "Inspect structure before mapping", "These are captured columns, types and relationships, not source business records.")),
    "database_delete": tour("Delete a database connection", ('#page-content form', "Review deletion", "Check the connection name and local snapshot history before confirming. Deletion does not remove tables or records from PostgreSQL.")),
    "document_delete": tour("Delete a document or extraction", ('#page-content form', "Review what will be removed", "Read the confirmation and related record restrictions before deleting. Cancel to retain the saved evidence.")),
})


def for_page(request):
    """Use route identity, not URL IDs or document contents, to choose the guide."""
    match = request.resolver_match
    name = match.url_name or ""
    namespace = match.namespace
    key = "setup"
    if namespace == "DOC_EXTRACTION":
        if name.endswith("_delete"):
            key = "document_delete"
        elif name == "document_upload":
            key = "upload"
        elif name == "document_edit":
            key = "edit_document"
        elif "extraction" in name:
            key = "extraction"
        elif name.startswith("batch"):
            key = "batches" if name == "batch_list" else "batch"
        else:
            key = "documents" if name == "document_list" else "document"
    elif namespace == "ROUTER":
        key = "destinations" if name.startswith("destination") else "rules" if name.startswith("rule") else "routing_logs" if name.startswith("log") else "route" if name == "document" else "queue"
    elif namespace == "ENCODER":
        key = {"dashboard": "encoder_queue", "workspace": "encoder_job", "connections": "encoder_connections",
               "connection_create": "encoder_connection_form", "connection_edit": "encoder_connection_form",
               "connection_detail": "encoder_connection", "mapping_edit": "encoder_mapping",
               "history": "encoder_history", "execution_detail": "encoder_history", "llm_logs": "logs", "llm_log_detail": "logs"}.get(name, "encoder_queue")
    elif namespace == "DB_EXTRACTION":
        key = {"source_create": "database_form", "source_edit": "database_form", "source_delete": "database_delete",
               "run_list": "database_runs", "run_detail": "database_run", "table_detail": "database_table"}.get(name, "database")
    elif namespace in {"ACCOUNTS_PAYABLE", "ACCOUNTS_RECEIVABLE"}:
        if name == "payment_allocate":
            key = "allocate"
        elif name == "reconciliation_match":
            key = "match"
        elif name.startswith("configuration"):
            key = "configurations" if name == "configuration_list" else "configuration_form"
        else:
            key = next((value for prefix, value in {"party": "parties", "purchase_order": "orders", "delivery_receipt": "deliveries", "invoice": "invoices", "payment": "payments", "reconciliation": "reconciliation", "aging": "aging", "llm_log": "logs", "overview": "overview"}.items() if name.startswith(prefix)), "overview")
    return GUIDES[key]
