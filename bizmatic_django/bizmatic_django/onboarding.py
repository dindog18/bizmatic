"""Workspace setup checks, reminder preferences and context-specific page help."""

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.http import HttpResponseBadRequest
from document_extraction.models import WorkspaceSetupPreferences, SETUP_MODULES, default_setup_modules
from django.core.exceptions import ImproperlyConfigured

from db_extraction.credentials import credential_cipher
from accounts_receivable.services.catalog import TARGETS
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

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


def checklist(active_modules=None):
    groups = []
    if active_modules is None:
        preference = WorkspaceSetupPreferences.objects.filter(pk=1).first()
        active_modules = preference.active_modules if preference else default_setup_modules()

    def group(key, title, description):
        value = {"key": key, "title": title, "description": description, "steps": []}
        groups.append(value)
        return value

    def step(group, title, ready, detail, route, label, optional=False):
        group["steps"].append({"title": title, "ready": ready, "detail": detail,
                               "url": reverse(route), "label": label, "optional": optional})

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
    assistant = group("CONFIG_ASSISTANT", "Configuration assistant", "A shared LLM builds and tests Record First document prompts and assists AP/AR query mapping and Encoder troubleshooting. Review and confirm configurations before activation.")
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
    encoder = group("ENCODER", "Encoder", "Prepare routed document payloads for approved MCP tools, then review and confirm every external execution.")
    step(encoder, "Enable local Encoder access", settings.ENCODER_LOCAL_ENABLED,
         "Set ENCODER_LOCAL_ENABLED=true and use a trusted loopback development server. Module activation here controls reminders; it does not override the local access restriction.", "ENCODER:dashboard", "Open Encoder")
    connections = apps.get_model("encoder", "MCPConnection").objects.filter(enabled=True).defer("environment", "http_headers")
    step(encoder, "Test and save an MCP connection", connections.filter(discovered_at__isnull=False, discovery_error="").exists(),
         "Choose STDIO or Streamable HTTP and enter its server details. Test and save discovers tools without calling business operations.", "ENCODER:connection_create", "Add MCP connection")
    permitted = any(set(row.approved_tools) & {tool["name"] for tool in row.tools} for row in connections)
    step(encoder, "Permit encoding operations", permitted, "Inspect discovered tool schemas and permit only intended encoding operations. Each execution still requires a separate payload confirmation.", "ENCODER:connections", "Review MCP tools")
    step(encoder, "Prepare encrypted secret storage (if needed)", key_ready,
         "Uses the same init_db_credential_key command as Database Connections. Needed only when saving secret environment variables or HTTP headers.", "ENCODER:connections", "Open connections", optional=True)
    ready, detail = provider_check("CONFIG_ASSISTANT")
    step(encoder, "Configure mapping and troubleshooting AI", ready, detail + " Encoder shares CONFIG_ASSISTANT_* settings.", "ENCODER:dashboard", "Open Encoder")
    encoder_destinations = destinations.filter(module_name="encoder", target_model="EncoderJob")
    step(encoder, "Route documents to Encoder", encoder_destinations.filter(rules__is_active=True).exists(),
         "Add an Encoder job destination and active rule in Router. Routing creates a draft; approve the current document and route, map fields, then explicitly confirm execution.", "ROUTER:destinations", "Review destinations")
    for position, item in enumerate(groups):
        item["position"] = position
        item["active"] = item["key"] in active_modules
        item["missing"] = sum(not row["ready"] and not row["optional"] for row in item["steps"])
    return groups



def workspace_guidance(request):
    match = request.resolver_match
    namespaces = {"DOC_EXTRACTION", "DB_EXTRACTION", "ROUTER", "ACCOUNTS_PAYABLE", "ACCOUNTS_RECEIVABLE", "ENCODER"}
    if not match or (match.namespace not in namespaces and match.url_name != "setup"):
        return {}
    if "/api/" in request.path:
        return {}
    preference = WorkspaceSetupPreferences.objects.filter(pk=1).first()
    groups = checklist(preference.active_modules if preference else default_setup_modules())
    current = next((group for group in groups if group["key"] == match.namespace), None)
    help_content = for_page(request)
    return {"setup_groups": groups, "setup_columns": [groups[::2], groups[1::2]], "setup_missing": sum(group["missing"] for group in groups if group["active"]),
            "setup_current": current if current and current["active"] else None,
            "setup_preferences_revision": preference.updated_at.isoformat() if preference else "", "page_help_title": help_content["title"], "page_guide": help_content}


@require_GET
def setup(request):
    return render(request, "document_extraction/setup.html", {"page_title": "Application setup", "section": "setup"})


@require_POST
def save_modules(request):
    selected = request.POST.getlist("active_modules")
    if set(selected) - set(SETUP_MODULES):
        return HttpResponseBadRequest("Choose only the listed modules.")
    try:
        with transaction.atomic():
            preference = WorkspaceSetupPreferences.objects.select_for_update().filter(pk=1).first()
            if request.POST.get("revision", "") != (preference.updated_at.isoformat() if preference else ""):
                messages.error(request, "Module selection changed. Review the current selection and save again.")
            else:
                preference = preference or WorkspaceSetupPreferences(pk=1)
                preference.active_modules = list(dict.fromkeys(selected))
                preference.save()
                messages.success(request, "Module selection saved. Setup reminders now include only active modules.")
    except IntegrityError:
        messages.error(request, "Module selection changed. Reload and try again.")
    return redirect("setup")
