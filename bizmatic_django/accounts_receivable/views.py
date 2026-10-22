"""GET-only frontend previews; accounting persistence is intentionally absent."""

from django.views.decorators.http import require_safe

from .ui import render_workspace


@require_safe
def workspace(request, **kwargs):
    return render_workspace(request, "ar", **kwargs)
