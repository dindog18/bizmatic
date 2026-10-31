"""Unauthenticated Encoder pages are available only on an enabled loopback site."""
from ipaddress import ip_address
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponseForbidden


class LocalEncoderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith("/encoder/"):
            peer_is_local = host_is_local = False
            try:
                peer_is_local = ip_address(request.META.get("REMOTE_ADDR", "")).is_loopback
                host = urlsplit("//" + request.get_host()).hostname
                host_is_local = host == "localhost" or ip_address(host).is_loopback
            except ValueError:
                host_is_local = False
            if not settings.ENCODER_LOCAL_ENABLED or not peer_is_local or not host_is_local:
                return HttpResponseForbidden("Encoder is available only when ENCODER_LOCAL_ENABLED=true on a trusted loopback development server.")
        return self.get_response(request)
