"""Component tours. Missing or hidden targets are skipped by help-tour.js."""


def tour(title, *steps):
    return {"title": title, "steps": [dict(zip(("selector", "title", "text"), step)) for step in steps]}


TABLE = ("#page-content table", "Read the records", "Each row is one saved record. Open its link to inspect the details.")
SEARCH = ('#page-content input[type="search"]', "Find a record", "Type a name or reference here to narrow the list.")
SAVE = ('#page-content form button[type="submit"]', "Save your changes", "After checking the fields, use this button to save. This tour does not submit forms.")
NAV = (".finance-nav", "Choose a workspace page", "Use these tabs to move between records, reconciliation, extraction setup and LLM activity.")
GUIDES = {
    "setup": tour("Application setup",
        ("#page-content .alert", "Check what is missing", "This count shows setup steps that still need attention."),
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
        ('[data-routing-trigger="document"]', "Send it to routing", "Route document proposes destinations. You will review those destinations before accounting processing.")),
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
        ('[data-review-form] button[value="approved"]', "Approve only after checking", "Approving a destination starts accounting extraction with a submitted document configuration."),
        ('#router-root select', "Choose the extraction profile", "If several profiles match, choose the one appropriate for this document."),
        ("#router-root .card", "Inspect the result", "Review status is your decision; processing status tracks creation of the accounting record. Read any errors before retrying.")),
    "destinations": tour("Routing destinations", SEARCH, TABLE,
        ("#router-name", "Name the destination", "Use a label reviewers recognize, such as Supplier invoices."),
        ("#router-module_name", "Select the module", "Choose Accounts payable or Accounts receivable."),
        ("#router-target_model", "Select the record type", "This is the type of record accounting extraction will create."),
        ("#router-active", "Enable routing to this destination", "Only active destinations are considered. Add active rules and a submitted extraction profile too."), SAVE),
    "rules": tour("Routing rules", SEARCH, TABLE,
        ("#router-name", "Name the rule", "Choose a name that explains what this rule recognizes."),
        ("#router-destination", "Choose a destination", "This rule will recommend the selected module and record type."),
        ("#router-instructions", "Explain what should match", "Describe the issuer, recipient and evidence to include. State when this destination should be excluded."),
        ("#router-examples", "Add useful examples", "Give examples of documents that should and should not match."),
        ("#router-active", "Activate the rule", "Only active rules for active destinations are used."), SAVE),
    "routing_logs": tour("Routing history", SEARCH, TABLE,
        ("#router-root pre", "Inspect the attempt", "Compare the saved input and response with the intended routing result.")),
    "database": tour("Database metadata", SEARCH, TABLE,
        ('#page-content a[href$="/new/"]', "Add a connection", "Save a PostgreSQL connection before testing it and refreshing metadata."),
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


def for_page(request):
    """Use route identity, not URL IDs or document contents, to choose the guide."""
    match = request.resolver_match
    name = match.url_name or ""
    namespace = match.namespace
    key = "setup"
    if namespace == "DOC_EXTRACTION":
        if name == "document_upload":
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
    elif namespace == "DB_EXTRACTION":
        key = "database_form" if name in {"source_create", "source_edit"} else "database"
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
