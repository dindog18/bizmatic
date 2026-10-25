"""Connection forms shared by the workspace and Django admin."""

from typing import Any

from django import forms
from django.core.exceptions import ImproperlyConfigured

from .credentials import credential_cipher
from .models import DatabaseSource
from .services.postgres import InspectionError, test_connection

CONNECTION_IDENTITY_FIELDS = ("host", "port", "database_name", "username", "ssl_mode", "ssl_root_cert")


class DatabaseSourceForm(forms.ModelForm):
    password = forms.CharField(
        required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Leave blank to keep the saved password only if the connection and SSL settings are unchanged.",
    )
    clear_password = forms.BooleanField(required=False, label="Clear saved password")
    included_schemas = forms.CharField(
        required=False, label="Schemas",
        help_text="Comma-separated names, for example public, accounting. Leave empty for all accessible non-system schemas.",
    )
    connect_timeout = forms.IntegerField(min_value=1, max_value=60, initial=10, label="Connection timeout (seconds)")

    class Meta:
        model = DatabaseSource
        fields = ["name", "host", "port", "database_name", "username", "password", "clear_password",
                  "ssl_mode", "ssl_root_cert", "connect_timeout", "included_schemas", "enabled"]
        help_texts = {"host": "Hostname, IP address, or a PostgreSQL Unix socket directory."}
        labels = {"ssl_mode": "SSL mode", "ssl_root_cert": "SSL root certificate"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection_result: dict[str, Any] | None = None
        # ModelForm updates its instance after cleaning; retain the original destination.
        self._saved_connection_identity = {name: getattr(self.instance, name) for name in CONNECTION_IDENTITY_FIELDS}
        if not self.instance.pk:
            self.fields.pop("clear_password", None)
        schemas = self.instance.included_schemas if self.instance.pk else []
        self.initial["included_schemas"] = ", ".join(schemas)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-select" if isinstance(field.widget, forms.Select) else "form-control"

    def clean_included_schemas(self):
        return list(dict.fromkeys(name.strip() for name in self.cleaned_data["included_schemas"].split(",") if name.strip()))

    def clean(self):
        cleaned = super().clean() or {}
        password = cleaned.get("password", "")
        if cleaned.get("clear_password"):
            if password:
                self.add_error("password", "Enter a new password or clear it, not both.")
            cleaned["password"] = ""
        elif not password and self.instance.pk:
            changed = any(cleaned[name] != value for name, value in self._saved_connection_identity.items() if name in cleaned)
            if self.instance.password and changed:
                self.add_error("password", "The connection or SSL settings changed. Enter the password again or choose Clear saved password before testing or saving.")
            else:
                cleaned["password"] = self.instance.password
        if not self.errors:
            # Verify exactly the submitted values, never a prior test result.
            candidate = DatabaseSource(**{name: cleaned[name] for name in DatabaseSourceForm.Meta.fields if name != "clear_password"})
            try:
                self.connection_result = test_connection(candidate)
                if cleaned.get("password"):
                    credential_cipher()
            except InspectionError as error:
                self.add_error(None, str(error))
            except ImproperlyConfigured:
                self.add_error(None, "The credential key is unavailable. Ask an administrator to provision or restore it.")
        return cleaned
