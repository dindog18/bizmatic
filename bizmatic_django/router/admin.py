from django.contrib import admin

from .models import DocumentRoute, LLMRoutingLog, RoutingDestination, RoutingRule


admin.site.register([RoutingDestination, RoutingRule, LLMRoutingLog, DocumentRoute])
