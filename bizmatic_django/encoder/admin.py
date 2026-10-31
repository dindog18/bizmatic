from django.contrib import admin
from .models import MCPConnection, EncoderJob, EncoderMapping, EncoderExecution, EncoderChatMessage, EncoderReset

# Admin is an audit viewer; configuration and execution use the guarded local workspace.
class AuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

for model in (MCPConnection, EncoderJob, EncoderMapping, EncoderExecution, EncoderChatMessage, EncoderReset):
    admin.site.register(model, AuditAdmin)
