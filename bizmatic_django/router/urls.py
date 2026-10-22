from django.urls import path

from . import views

app_name = "ROUTER"
urlpatterns = [
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
