"""HTTP handlers; routing work and database writes live in services/."""

import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_safe
from pydantic import ValidationError as SchemaError

from .models import DocumentRoute, RoutingDestination, RoutingRule
from .schemas.routing import ExecutionRequest
from .services import configuration, execution, pages, records, handoff
from .services.catalog import destination_catalog


def _perform(request, action):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return JsonResponse(action(data))
    except execution.ConfirmationRequired as error:
        return JsonResponse({"message": error.messages[0], "confirmation_required": True,
                             "documents": error.documents}, status=409)
    except SchemaError:
        return JsonResponse({"message": "Invalid routing request. Reload the page and check your selection and settings."}, status=400)
    except (ValidationError, ValueError, TypeError, OverflowError) as error:
        message = "; ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        status = 409 if isinstance(error, ValidationError) and getattr(error, "code", None) == "conflict" else 400
        return JsonResponse({"message": message}, status=status)


@require_safe
def workspace(request, screen="queue", record_id=None):
    titles = {
        "queue": "Document routing", "document": "Review routing",
        "destinations": "Routing destinations", "destination_create": "Add destination",
        "destination_edit": "Edit destination", "rules": "Routing rules",
        "rule_create": "Add routing rule", "rule_edit": "Edit routing rule",
        "logs": "LLM routing history", "log": "Routing attempt",
    }
    if screen in {"destination_edit", "rule_edit"}:
        get_object_or_404(RoutingDestination.objects.filter(is_deleted=False) if screen == "destination_edit" else RoutingRule, pk=record_id)
    routes = {
        name: reverse(f"ROUTER:{name}", args=[0] if name in {"document", "destination_edit", "rule_edit", "log"} else [])
        for name in titles
    }
    api = {"execute": reverse("ROUTER:execute"),
           "configuration": reverse("ROUTER:configuration_save", args=["destinations"]),
           "configurationEdit": reverse("ROUTER:configuration_edit", args=["destinations", 0]),
           "delete": reverse("ROUTER:configuration_delete", args=["destinations", 0]),
           "toggle": reverse("ROUTER:configuration_toggle", args=["destinations", 0]),
           "review": reverse("ROUTER:route_review", args=[0]),
           "process": reverse("ROUTER:route_process", args=[0]),
           "addRoute": reverse("ROUTER:route_add", args=[0]),
           "accuracy": reverse("ROUTER:log_accuracy", args=[0])}
    return render(request, "router/workspace.html", {
        "page_title": titles[screen], "section": "router",
        "router_config": {"screen": screen, "recordId": record_id, "routes": routes, "api": api,
                          "destinationCatalog": destination_catalog(),
                          "csrfToken": get_token(request), "documentsUrl": reverse("DOC_EXTRACTION:document_list")},
        "router_state": pages.workspace_state(screen, record_id),
    })


@require_POST
def execute(request):
    def run(data):
        logs = execution.execute(ExecutionRequest.model_validate(data))
        completed = sum(log.status == "completed" for log in logs)
        failed = sum(log.status == "failed" for log in logs)
        message = f"Routing finished: {completed} completed, {failed} failed, {len(logs) - completed - failed} still running."
        routes = DocumentRoute.objects.filter(routing_log__in=logs)
        statuses = list(routes.exclude(destination__module_name="encoder").values_list("processing_status", flat=True))
        encoder_statuses = list(routes.filter(destination__module_name="encoder").values_list("processing_status", flat=True))
        encoder = {status: encoder_statuses.count(status) for status in ("completed", "failed", "pending", "processing")}
        accounting = {status: statuses.count(status) for status in ("completed", "failed", "pending", "processing")}
        if statuses:
            message += f" Accounting extraction: {accounting['completed']} completed, {accounting['failed']} failed, {accounting['pending'] + accounting['processing']} waiting."
        if encoder_statuses:
            message += f" Encoder draft handoff: {encoder['completed']} created, {encoder['failed']} failed. External execution requires review and confirmation."
        (messages.warning if accounting["failed"] or encoder["failed"] else messages.info)(request, message)
        return {"message": message, "logs": [{"id": row.pk, "status": row.status} for row in logs],
                "accounting": accounting, "encoder": encoder,
                "redirect": reverse("ROUTER:document", args=[logs[0].source_document_id]) if len(logs) == 1 else reverse("ROUTER:queue")}
    return _perform(request, run)


@require_POST
def configuration_save(request, kind, record_id=None):
    if kind not in configuration.MODELS:
        raise Http404
    serialize = pages.destination if kind == "destinations" else pages.rule
    def save(data):
        row = configuration.save(kind, data, record_id)
        messages.success(request, f"{row.name} saved.")
        return {"record": serialize(row)}
    return _perform(request, save)


@require_POST
def configuration_toggle(request, kind, record_id):
    if kind not in configuration.MODELS:
        raise Http404
    serialize = pages.destination if kind == "destinations" else pages.rule
    return _perform(request, lambda data: {"record": serialize(configuration.toggle(kind, record_id, data))})


@require_POST
def route_review(request, route_id):
    def review(data):
        route = records.review(route_id, data)
        if data.get("decision") == "approved":
            route = handoff.process(route_id)
        return {"record": pages.route(route)}
    return _perform(request, review)


@require_POST
def route_process(request, route_id):
    def process(data):
        if not isinstance(data.get("revision"), str) or not data["revision"]:
            raise ValidationError("Reload the route before retrying extraction.")
        # An explicit retry may resume an automatic handoff without recording a
        # human approval. Rejected, stale, and superseded routes remain blocked.
        return {"record": pages.route(handoff.process(route_id,
            configuration_id=data.get("configuration_id"), revision=data["revision"], automatic=True))}
    return _perform(request, process)


@require_POST
def route_add(request, log_id):
    return _perform(request, lambda data: {"record": pages.route(records.add_route(log_id, data))})


@require_POST
def log_accuracy(request, log_id):
    return _perform(request, lambda data: {"record": pages.log(records.set_accuracy(log_id, data), full=True)})


@require_POST
def configuration_delete(request, kind, record_id):
    if kind not in configuration.MODELS:
        raise Http404
    return _perform(request, lambda data: {"deleted_id": configuration.delete(kind, record_id, data)})
