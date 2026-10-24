from accounts_receivable.ui import workspace_patterns

from . import views

app_name = "ACCOUNTS_PAYABLE"
urlpatterns = workspace_patterns(views.workspace, "suppliers", views.api)
