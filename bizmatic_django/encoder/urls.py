from django.urls import path
from . import views

app_name = "ENCODER"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("jobs/<int:job_id>/", views.workspace, name="workspace"),
    path("jobs/<int:job_id>/<str:action>/", views.job_action, name="job_action"),
    path("connections/", views.connections, name="connections"),
    path("connections/new/", views.connection_edit, name="connection_create"),
    path("connections/<int:connection_id>/", views.connection_detail, name="connection_detail"),
    path("connections/<int:connection_id>/edit/", views.connection_edit, name="connection_edit"),
    path("connections/<int:connection_id>/mappings/<str:tool_name>/", views.mapping_edit, name="mapping_edit"),
    path("llm-logs/", views.llm_logs, name="llm_logs"),
    path("llm-logs/<int:message_id>/", views.llm_log_detail, name="llm_log_detail"),
    path("history/", views.history, name="history"),
    path("history/<int:execution_id>/", views.execution_detail, name="execution_detail"),
]
