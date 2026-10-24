"""Read-only setup checklist and page help for the five workspaces."""

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured

from db_extraction.credentials import credential_cipher
from accounts_receivable.services.catalog import TARGETS
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .environment import get_env
from .page_help import for_page

PROVIDERS = {
    "openai": "OPENAI", "anthropic": "ANTHROPIC", "google": "GOOGLE",
    "ollama": None, "alibaba": "DASHSCOPE", "deepseek": "DEEPSEEK",
    "mistral": "MISTRAL",
}


def filled(value):
    return bool(value.strip()) and not value.lower().startswith(("replace-", "your-"))


def provider_check(prefix):
    """Check required settings without returning credential values or calling providers."""
    missing = []
    providers = get_env(prefix + "_LLM_PROVIDER", "ollama" if prefix != "DOC_EXTRACTION" else "").lower().split(",")
    if prefix != "DOC_EXTRACTION" and len(providers) != 1:
        return False, "Choose one chat provider in " + prefix + "_LLM_PROVIDER."
    for provider in providers:
        provider = provider.strip()
        if provider not in PROVIDERS or (provider == "mistral" and prefix != "DOC_EXTRACTION"):
            missing.append(prefix + "_LLM_PROVIDER (choose a supported provider)")
            continue
        model_key = "MISTRAL_OCR_MODEL" if provider == "mistral" else provider.upper() + "_MODEL"
        if not filled(get_env(prefix + "_" + model_key)):
            missing.append(prefix + "_" + model_key)
        key = PROVIDERS[provider]
        if key:
            name = key + "_API_KEY"
            value = get_env(prefix + "_" + name)
            if not value.strip() and prefix != "DOC_EXTRACTION":
                value = get_env("DOC_EXTRACTION_" + name)
            if not filled(value):
                missing.append(prefix + "_" + name)
    for suffix, default in [("LLM_TIMEOUT_SECONDS", "120"), ("MAX_INPUT_CHARACTERS", "150000"), ("MAX_OUTPUT_TOKENS", "8192")]:
        if prefix == "DOC_EXTRACTION" and suffix != "LLM_TIMEOUT_SECONDS":
            continue
        try:
            if int(get_env(prefix + "_" + suffix, default)) <= 0:
                raise ValueError
        except ValueError:
            missing.append(prefix + "_" + suffix + " (positive number)")
    return not missing, "Fill in: " + ", ".join(missing) + ". Restart Django after editing .env." if missing else "Required settings are present. Provider availability is checked when you run extraction."


def checklist():
    groups = []

    def group(key, title, description):
        value = {"key": key, "title": title, "description": description, "steps": []}
        groups.append(value)
        return value

    def step(group, title, ready, detail, route, label):
        group["steps"].append({"title": title, "ready": ready, "detail": detail,
                               "url": reverse(route), "label": label})

    doc = group("DOC_EXTRACTION", "Document extraction", "Upload files, extract text, and approve the result before routing.")
    ready, detail = provider_check("DOC_EXTRACTION")
    step(doc, "Configure the document LLM", ready, detail, "DOC_EXTRACTION:document_upload", "Upload documents")
    router = group("ROUTER", "Document routing", "Choose destinations and write rules that explain where documents belong.")
    ready, detail = provider_check("ROUTER")
    step(router, "Configure the routing LLM", ready, detail, "ROUTER:queue", "Open routing")
    destinations = apps.get_model("router", "RoutingDestination").objects.filter(is_active=True)
    step(router, "Add active destinations", destinations.exists(), "Choose a module and record type for every destination you need.", "ROUTER:destination_create", "Add destination")
    uncovered = list(destinations.exclude(rules__is_active=True).values_list("name", flat=True))
    rules_ready = destinations.exists() and not uncovered
    step(router, "Add active routing rules", rules_ready, "Add a rule for each destination. Missing rules: " + ", ".join(uncovered) if uncovered else "Rules describe which documents should match each destination.", "ROUTER:rules", "Review rules")
    for app, title in [("accounts_payable", "Accounts payable"), ("accounts_receivable", "Accounts receivable")]:
        namespace = app.upper()
        accounting = group(namespace, title, "Submit extraction instructions for each record type and source you plan to use.")
        ready, detail = provider_check(namespace)
        step(accounting, "Configure the module LLM", ready, detail, namespace + ":configuration_list", "Open extraction setup")
        configs = apps.get_model(app, "ExtractionConfiguration").objects.filter(status="submitted").exclude(submitted_snapshot={})
        step(accounting, "Submit an extraction configuration", configs.exists(), "Choose the target record, document or database source, field instructions or mappings, and account lookup. Save drafts, then review and submit.", namespace + ":configuration_create", "Add configuration")
        # Document routing needs a submitted document profile for each active target.
        targets = {name: key for key, name in TARGETS["ap" if app == "accounts_payable" else "ar"].items()}
        for destination in destinations.filter(module_name=app):
            target = targets.get(destination.target_model)
            ready = bool(target) and configs.filter(source_type="document", target_entity=target).exists()
            step(accounting, "Document profile: " + destination.name, ready, "Submit a document configuration for this target. If several profiles match, choose one during route review. Account-specific profiles require a matching account.", namespace + ":configuration_list", "Review configurations")
    assistant = group("CONFIG_ASSISTANT", "Configuration assistant", "A shared LLM builds and tests Record First document prompts and assists AP/AR query mapping. Review and confirm configurations before activation.")
    ready, detail = provider_check("CONFIG_ASSISTANT")
    step(assistant, "Configure the assistant LLM", ready, detail, "ACCOUNTS_PAYABLE:configuration_list", "Open extraction setup")
    database = group("DB_EXTRACTION", "Database extraction (optional)", "Only needed when importing from PostgreSQL. Document routing works without it.")
    try:
        credential_cipher()
        key_ready = True
    except ImproperlyConfigured:
        key_ready = False
    step(database, "Prepare encrypted credential storage", key_ready,
         "An administrator must run python manage.py init_db_credential_key from bizmatic_django before storing database passwords. Keep the original key backed up; restore it for existing connections.",
         "DB_EXTRACTION:source_list", "Open connections")
    sources = apps.get_model("db_extraction", "DatabaseSource").objects.filter(enabled=True)
    step(database, "Add an enabled connection", sources.exists(), "Enter host, port, database, username, password and SSL settings. Test the connection before refreshing metadata.", "DB_EXTRACTION:source_create", "Add connection")
    ready = apps.get_model("db_extraction", "ExtractionRun").objects.filter(source__enabled=True, status="completed").exists()
    step(database, "Refresh schema metadata", ready, "Open a connection and refresh metadata. Then select its tables and map fields in an AP or AR database configuration. Submit that configuration before importing.", "DB_EXTRACTION:source_list", "Open connections")
    for item in groups:
        item["missing"] = sum(not row["ready"] for row in item["steps"])
    return groups



def workspace_guidance(request):
    match = request.resolver_match
    namespaces = {"DOC_EXTRACTION", "DB_EXTRACTION", "ROUTER", "ACCOUNTS_PAYABLE", "ACCOUNTS_RECEIVABLE"}
    if not match or (match.namespace not in namespaces and match.url_name != "setup"):
        return {}
    if "/api/" in request.path:
        return {}
    groups = checklist()
    current = next((group for group in groups if group["key"] == match.namespace), None)
    help_content = for_page(request)
    return {"setup_groups": groups, "setup_missing": sum(group["missing"] for group in groups if group["key"] != "DB_EXTRACTION"),
            "setup_current": current, "page_help_title": help_content["title"], "page_guide": help_content}


@require_GET
def setup(request):
    return render(request, "document_extraction/setup.html", {"page_title": "Application setup", "section": "setup"})
