from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from encoder.models import MCPConnection
from encoder.services.mcp_client import http_specification


class TransportSecurityTests(SimpleTestCase):
    def test_remote_plain_http_is_rejected_before_credentials_are_loaded(self):
        for host in ("example.com", "192.168.1.20", "localhost.example.com", "[::ffff:192.0.2.1]"):
            with self.subTest(host=host), self.assertRaisesMessage(ValidationError, "HTTPS"):
                http_specification(MCPConnection(server_url=f"http://{host}/mcp", bearer_token_env_var="MISSING_TOKEN"))

    def test_loopback_http_and_remote_https_are_supported(self):
        for url in ("http://localhost:8080/mcp", "http://127.0.0.1/mcp", "http://[::1]/mcp", "https://example.com/mcp"):
            with self.subTest(url=url):
                self.assertEqual(http_specification(MCPConnection(server_url=url)).url, url)
