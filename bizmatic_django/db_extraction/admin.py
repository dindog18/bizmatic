"""Manage connection profiles; extracted snapshots are available for inspection."""

from django.contrib import admin

from .forms import DatabaseSourceForm

from .models import (
    ConstraintColumn, DatabaseColumn, DatabaseConstraint, DatabaseIndex,
    DatabaseSchema, DatabaseSource, DatabaseTable, ExtractionRun,
)


@admin.register(DatabaseSource)
class DatabaseSourceAdmin(admin.ModelAdmin):
    form = DatabaseSourceForm
    list_display = ("name", "host", "port", "database_name", "username", "enabled")
    list_filter = ("enabled", "ssl_mode")
    search_fields = ("name", "host", "database_name")
    readonly_fields = ("created_at", "updated_at")


class SnapshotAdmin(admin.ModelAdmin):
    """Snapshots are written by extraction services, not edited through admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ExtractionRun)
class ExtractionRunAdmin(SnapshotAdmin):
    list_display = ("id", "source", "status", "database_name", "created_at", "finished_at")
    list_filter = ("status", "source")
    list_select_related = ("source",)


for model in (DatabaseSchema, DatabaseTable, DatabaseColumn, DatabaseConstraint, ConstraintColumn, DatabaseIndex):
    admin.site.register(model, SnapshotAdmin)
