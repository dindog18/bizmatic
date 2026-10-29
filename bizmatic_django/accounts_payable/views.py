"""Accounting page handlers; persistence lives in services/."""

from django.views.decorators.http import require_POST, require_safe
from accounts_receivable.ui import render_workspace
from accounts_receivable.services.http import perform


@require_safe
def workspace(request, **kwargs):
    return render_workspace(request, "ap", **kwargs)


@require_POST
def api(request, action, record_id=None):
    return perform(request, "ap", action, record_id)
