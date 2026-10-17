"""Database workspace routes; all mutations are POST-only and CSRF protected."""

from django.urls import path

from . import views

app_name = "DB_EXTRACTION"
urlpatterns = [
    path("", views.source_list, name="source_list"),
    path("new/", views.source_form, name="source_create"),
    path("<int:source_id>/", views.source_detail, name="source_detail"),
    path("<int:source_id>/edit/", views.source_form, name="source_edit"),
    path("<int:source_id>/test/", views.source_test, name="source_test"),
    path("<int:source_id>/refresh/", views.source_refresh, name="source_refresh"),
    path("<int:source_id>/delete/", views.source_delete, name="source_delete"),
    path("<int:source_id>/runs/", views.run_list, name="run_list"),
    path("<int:source_id>/runs/<int:run_id>/", views.run_detail, name="run_detail"),
    path("<int:source_id>/runs/<int:run_id>/tables/<int:table_id>/", views.table_detail, name="table_detail"),
]
