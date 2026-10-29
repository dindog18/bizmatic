"""Keep old Record First bookmarks pointing at the production AP/AR setup."""
from urllib.parse import urlencode
from django.shortcuts import redirect
from django.urls import path, reverse

app_name = 'CONFIGURATION_LAB'


def record_first(request):
    mode = 'ar' if request.GET.get('module') == 'ar' else 'ap'
    namespace = 'ACCOUNTS_RECEIVABLE' if mode == 'ar' else 'ACCOUNTS_PAYABLE'
    target = request.GET.get('record') or request.GET.get('target') or ('customer' if mode == 'ar' else 'supplier')
    source = request.GET.get('source', 'document')
    return redirect(reverse(namespace+':configuration_create')+'?'+urlencode({'target': target, 'source': source}))


urlpatterns = [path('', record_first, name='gallery'), path('record-preview/', record_first, name='record-preview')]
