"""GET-only shells for the router preview; sample data lives in the browser."""

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe


@require_safe
def workspace(request, screen="queue", record_id=None):
    titles = {
        "queue": "Document routing", "document": "Review routing",
        "destinations": "Routing destinations", "destination_create": "Add destination",
        "destination_edit": "Edit destination", "rules": "Routing rules",
        "rule_create": "Add routing rule", "rule_edit": "Edit routing rule",
        "logs": "LLM routing history", "log": "Routing attempt",
    }
    routes = {
        name: reverse(f"ROUTER:{name}", args=[0] if name in {
            "document", "destination_edit", "rule_edit", "log",
        } else [])
        for name in titles
    }
    return render(request, "router/workspace.html", {
        "page_title": titles[screen], "section": "router",
        "router_config": {"screen": screen, "recordId": record_id, "routes": routes,
                          "documentsUrl": reverse("DOC_EXTRACTION:document_list")},
    })
