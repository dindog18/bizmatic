from django.urls import path

from . import views

app_name = "ROUTER"
urlpatterns = [
    path("execute/", views.execute, name="execute"),
    path("api/configuration/<str:kind>/", views.configuration_save, name="configuration_save"),
    path("api/configuration/<str:kind>/<int:record_id>/", views.configuration_save, name="configuration_edit"),
    path("api/configuration/<str:kind>/<int:record_id>/toggle/", views.configuration_toggle, name="configuration_toggle"),
    path("api/routes/<int:route_id>/review/", views.route_review, name="route_review"),
    path("api/logs/<int:log_id>/routes/", views.route_add, name="route_add"),
    path("api/logs/<int:log_id>/accuracy/", views.log_accuracy, name="log_accuracy"),
    path("", views.workspace, name="queue"),
    path("documents/<int:record_id>/", views.workspace, {"screen": "document"}, name="document"),
    path("destinations/", views.workspace, {"screen": "destinations"}, name="destinations"),
    path("destinations/new/", views.workspace, {"screen": "destination_create"}, name="destination_create"),
    path("destinations/<int:record_id>/edit/", views.workspace, {"screen": "destination_edit"}, name="destination_edit"),
    path("rules/", views.workspace, {"screen": "rules"}, name="rules"),
    path("rules/new/", views.workspace, {"screen": "rule_create"}, name="rule_create"),
    path("rules/<int:record_id>/edit/", views.workspace, {"screen": "rule_edit"}, name="rule_edit"),
    path("logs/", views.workspace, {"screen": "logs"}, name="logs"),
    path("logs/<int:record_id>/", views.workspace, {"screen": "log"}, name="log"),
]
