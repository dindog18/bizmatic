from . import views
from .ui import workspace_patterns

app_name = "ACCOUNTS_RECEIVABLE"
urlpatterns = workspace_patterns(views.workspace, "customers")
