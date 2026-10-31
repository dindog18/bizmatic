"""Browser-rendered form revisions must not be localized timestamps."""
from html.parser import HTMLParser

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import MCPConnection


class HiddenInputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.revisions = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "revision":
            self.revisions.append(attrs["value"])


@override_settings(ENCODER_LOCAL_ENABLED=True, ALLOWED_HOSTS=["localhost"], TIME_ZONE="Asia/Manila")
class ConnectionRevisionTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="localhost")
        self.connection = MCPConnection.objects.create(name="Synthetic HTTP", transport="streamable_http", server_url="https://example.test/mcp", tools=[{"name": "synthetic_operation", "inputSchema": {"type": "object"}}])
        self.url = reverse("ENCODER:connection_detail", args=[self.connection.pk])

    def rendered_revision(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return HiddenInputs(response.content.decode()).revisions[0]

    def test_browser_form_saves_selection_in_non_utc_timezone(self):
        for zone in ("Asia/Manila", "America/New_York", "UTC"):
            with timezone.override(zone):
                self.connection.refresh_from_db()
                revision = self.rendered_revision()
                self.assertEqual(revision, self.connection.updated_at.isoformat())
                response = self.client.post(self.url, {"intent": "approve", "revision": revision, "approved_tools": ["synthetic_operation"]}, follow=True)
                self.assertContains(response, "Permitted operations saved.")
                self.assertNotContains(response, "The connection changed.")
                self.connection.refresh_from_db()
                self.assertEqual(self.connection.approved_tools, ["synthetic_operation"])

    def test_real_changes_still_reject_old_browser_form(self):
        revision = self.rendered_revision()
        self.connection.timeout_seconds = 60
        self.connection.save()
        response = self.client.post(self.url, {"intent": "approve", "revision": revision, "approved_tools": ["synthetic_operation"]}, follow=True)
        self.assertContains(response, "The connection changed.")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.approved_tools, [])
