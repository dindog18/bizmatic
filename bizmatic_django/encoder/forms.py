"""Falcon-styled Django forms built from discovered tool schemas."""
import json

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from db_extraction.credentials import credential_cipher

from .models import MCPConnection
from .services import mapping


class StyledForm(forms.Form):
    def style(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-select" if isinstance(field.widget, forms.Select) else "form-control"


class ConnectionForm(forms.ModelForm):
    transport = forms.ChoiceField(choices=MCPConnection._meta.get_field("transport").choices, required=False, initial="stdio")
    server_url = forms.URLField(required=False, max_length=2000, label="Server URL", assume_scheme="https", help_text="Streamable HTTP endpoint, e.g. https://example.com/mcp.")
    bearer_token_env_var = forms.CharField(required=False, label="Bearer token environment variable", help_text="Name of an environment variable on the Django server containing the bearer token.")
    http_headers = forms.CharField(required=False, strip=False, widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}), label="HTTP headers (secret JSON)", help_text='Optional literal headers as JSON, e.g. {"X-API-Key":"value"}. Encrypted at rest; blank preserves unchanged settings.')
    clear_http_headers = forms.BooleanField(required=False, label="Clear saved HTTP headers")
    env_http_headers = forms.JSONField(required=False, initial=dict, widget=forms.Textarea(attrs={"rows": 2}), label="HTTP headers from environment variables", help_text='Optional JSON map of header names to environment variable names, e.g. {"X-API-Key":"ERP_API_KEY"}.')
    environment_passthrough = forms.JSONField(required=False, initial=list, label="Environment variable passthrough", help_text="Names of variables to forward from the Django server environment.")
    arguments = forms.JSONField(required=False, initial=list, widget=forms.Textarea(attrs={"rows": 3}),
        help_text='JSON list of arguments, e.g. ["/path/to/server.py"]. No shell expansion is performed.')
    environment = forms.CharField(required=False, strip=False, widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        label="Environment variables (secret JSON)", help_text='JSON object, e.g. {"ERP_API_KEY":"value"}. Encrypted at rest. Leave blank to keep saved values only when launch details are unchanged.')
    clear_environment = forms.BooleanField(required=False, label="Clear saved environment variables")
    timeout_seconds = forms.IntegerField(min_value=1, max_value=300, initial=30)
    command = forms.CharField(required=False, max_length=1000, help_text="Server executable, e.g. /absolute/path/to/python or npx.")

    class Meta:
        model = MCPConnection
        fields = ["name", "transport", "server_url", "bearer_token_env_var", "http_headers", "clear_http_headers", "env_http_headers", "command", "arguments", "working_directory", "environment", "environment_passthrough", "clear_environment", "timeout_seconds", "enabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection_result = None
        self.saved_identity = (self.instance.command, self.instance.arguments, self.instance.working_directory, self.instance.environment_passthrough)
        self.saved_http_identity = (self.instance.transport, self.instance.server_url, self.instance.bearer_token_env_var, self.instance.env_http_headers)
        self.saved_http_headers = self.instance.http_headers
        self.initial["http_headers"] = ""
        self.saved_environment = self.instance.environment
        self.initial["environment"] = ""
        if not self.instance.pk:
            self.fields.pop("clear_environment", None)
            self.fields.pop("clear_http_headers", None)
        self.fields["name"].widget.attrs["placeholder"] = "MCP server name"
        self.fields["command"].label = "Command to launch"
        self.fields["command"].widget.attrs["placeholder"] = "openai-dev-mcp serve-sqlite"
        self.fields["server_url"].label = "URL"
        self.fields["server_url"].widget.attrs["placeholder"] = "https://mcp.example.com/mcp"
        self.fields["bearer_token_env_var"].label = "Bearer token env var"
        self.fields["bearer_token_env_var"].widget.attrs["placeholder"] = "MCP_BEARER_TOKEN"
        self.fields["environment"].label = "Environment variables"
        self.fields["http_headers"].label = "Headers"
        self.fields["env_http_headers"].label = "Headers from environment variables"
        self.fields["arguments"].help_text = "One argument per row; values are passed exactly as entered, without shell expansion."
        self.fields["environment"].help_text = "Values are encrypted. Leave rows empty to keep saved values for unchanged launch details, or use Clear saved environment variables. Entering rows replaces the saved set."
        self.fields["http_headers"].help_text = "Values are encrypted. Leave rows empty to keep saved headers for an unchanged destination, or use Clear saved HTTP headers. Entering rows replaces the saved set."
        self.fields["env_http_headers"].help_text = "Header name on the left, Django server environment variable name on the right."
        StyledForm.style(self)

    def clean(self):
        values = super().clean()
        values["transport"] = values.get("transport") or "stdio"
        http = values["transport"] == "streamable_http"
        if http:
            values.update(command="", arguments=[], working_directory="", environment="", environment_passthrough=[])
            if not values.get("server_url"):
                self.add_error("server_url", "Enter the Streamable HTTP endpoint URL.")
        else:
            values.update(server_url="", bearer_token_env_var="", http_headers="", env_http_headers={})
            if not values.get("command"):
                self.add_error("command", "Enter the server executable.")
        values["env_http_headers"] = {} if values.get("env_http_headers") is None else values["env_http_headers"]
        headers = values.get("http_headers", "")
        http_identity = (values["transport"], values.get("server_url"), values.get("bearer_token_env_var"), values["env_http_headers"])
        if http and values.get("clear_http_headers"):
            if headers:
                self.add_error("http_headers", "Enter new headers or clear saved headers, not both.")
            headers = ""
        elif http and not headers and self.instance.pk:
            if self.saved_http_headers and http_identity != self.saved_http_identity:
                self.add_error("http_headers", "HTTP destination or authentication changed. Re-enter or clear saved headers.")
            else:
                headers = self.saved_http_headers
        values["http_headers"] = headers
        values["arguments"] = [] if values.get("arguments") is None else values["arguments"]
        if not isinstance(values["arguments"], list) or any(not isinstance(arg, str) for arg in values["arguments"]):
            self.add_error("arguments", "Enter a JSON list of strings.")
        values["environment_passthrough"] = [] if values.get("environment_passthrough") is None else values["environment_passthrough"]
        environment = values.get("environment", "")
        identity = (values.get("command"), values.get("arguments"), values.get("working_directory", ""), values.get("environment_passthrough") or [])
        if values.get("clear_environment"):
            if environment:
                self.add_error("environment", "Enter new values or clear saved values, not both.")
            environment = ""
        elif not http and not environment and self.instance.pk:
            if self.saved_environment and identity != self.saved_identity:
                self.add_error("environment", "Launch details changed. Re-enter environment variables or explicitly clear them before testing.")
            else:
                environment = self.saved_environment
        values["environment"] = environment
        if not self.errors:
            from .services import mcp_client
            from .services.validation import check_schema
            candidate = MCPConnection(**{name: values[name] for name in ("transport", "server_url", "bearer_token_env_var", "http_headers", "env_http_headers", "command", "arguments", "working_directory", "environment", "environment_passthrough", "timeout_seconds")}, enabled=True)
            try:
                mcp_client.specification(candidate)
                if environment or headers:
                    credential_cipher()
                self.connection_result = mcp_client.connector(candidate).discover()
                for tool in self.connection_result:
                    check_schema(tool.get("inputSchema"))
            except ValidationError as error:
                self.add_error(None, "; ".join(error.messages))
            except ImproperlyConfigured:
                self.add_error(None, "The credential key is unavailable. Provision or restore it using init_db_credential_key, as for Database Connections.")
        return values


class OperationForm(StyledForm):
    connection = forms.ModelChoiceField(queryset=MCPConnection.objects.none())
    tool_name = forms.ChoiceField(label="Permitted operation")
    revision = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, job, selected_connection=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["connection"].queryset = MCPConnection.objects.filter(enabled=True)
        selected = self.data.get("connection") if self.is_bound else selected_connection or job.connection_id
        connection = self.fields["connection"].queryset.filter(pk=selected).first() if str(selected or "").isdigit() else None
        self.fields["tool_name"].choices = [("", "Choose an operation")] + [(row["name"], row.get("title") or row["name"]) for row in (connection.tools if connection else []) if row["name"] in connection.approved_tools]
        self.initial.update(connection=selected, tool_name=job.tool_name, revision=job.updated_at.isoformat())
        self.style()


class PayloadForm(StyledForm):
    """Top-level scalars have ordinary inputs; nested fields retain arbitrary JSON."""
    revision = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, job, **kwargs):
        super().__init__(*args, **kwargs)
        self.parameters = []
        for index, (name, schema) in enumerate(job.tool_schema.get("properties", {}).items()):
            key = f"value_{index}"
            required = name in job.tool_schema.get("required", [])
            kind = schema.get("type")
            label = (schema.get("title") or name) + (" · required" if required else " · optional")
            common = {"label": label, "required": False, "help_text": schema.get("description", "")}
            if "enum" in schema:
                field = forms.TypedChoiceField(choices=[("", "Not supplied")] + [(json.dumps(v), str(v)) for v in schema["enum"]], coerce=json.loads, empty_value=None, **common)
                initial = json.dumps(job.prepared_payload[name]) if name in job.prepared_payload else ""
            elif kind == "boolean":
                field = forms.TypedChoiceField(choices=[("", "Not supplied"), ("true", "Yes"), ("false", "No")], coerce=json.loads, empty_value=None, **common)
                initial = json.dumps(job.prepared_payload[name]) if name in job.prepared_payload else ""
            else:
                cls = {"integer": forms.IntegerField, "number": forms.FloatField, "string": forms.CharField}.get(kind, forms.JSONField)
                field = cls(**common)
                if cls is forms.JSONField:
                    field.widget = forms.Textarea(attrs={"rows": 3})
                initial = job.prepared_payload.get(name)
            self.fields[key] = field
            self.initial[key] = initial
            self.parameters.append((name, key))
        self.initial["revision"] = job.updated_at.isoformat()
        self.style()

    def payload(self, job):
        result = dict(job.prepared_payload)
        for name, key in self.parameters:
            value = self.cleaned_data[key]
            if value is None or value == "":
                result.pop(name, None)
            else:
                result[name] = value
        return result


class MappingForm(StyledForm):
    revision = forms.CharField(widget=forms.HiddenInput)
    reusable = forms.BooleanField(required=False, label="Save these mappings for future documents using this connection and operation")

    def __init__(self, *args, job, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []
        paths = []
        def collect(value, path="", depth=0):
            if depth > 8 or len(paths) > 200:
                return
            if path:
                paths.append(path)
            children = value.items() if isinstance(value, dict) else enumerate(value[:20]) if isinstance(value, list) else []
            for key, child in children:
                collect(child, f"{path}.{key}".strip("."), depth + 1)
        collect(mapping.source_data(job))
        names = list(dict.fromkeys([*job.tool_schema.get("properties", {}), *job.field_mappings]))[:200]
        for index, name in enumerate(names):
            rule = job.field_mappings.get(name, {})
            source, default, transform = (f"{part}_{index}" for part in ("source", "default", "transform"))
            choices = list(dict.fromkeys([*paths, *([rule["source"]] if rule.get("source") else [])]))
            self.fields[source] = forms.ChoiceField(label=f"{name} · source", choices=[("", "No source / use default")] + [(path, path) for path in choices], required=False, initial=rule.get("source", ""))
            self.fields[default] = forms.JSONField(label=f"{name} · default (JSON)", required=False, initial=rule.get("default"), widget=forms.TextInput, help_text='Explicit fallback, e.g. 2 or "PHP". Leave blank when unknown.')
            self.fields[transform] = forms.ChoiceField(label=f"{name} · transformation", choices=[(v, v.replace("_", " ")) for v in mapping.TRANSFORMS], initial=rule.get("transform", "identity"))
            self.rows.append((name, source, default, transform))
        self.initial["revision"] = job.updated_at.isoformat()
        self.style()

    def mappings(self):
        result = {}
        for name, source, default, transform in self.rows:
            values = self.cleaned_data
            if values[source] or self.data.get(default, "").strip():
                result[name] = {"source": values[source], "transform": values[transform]}
                if self.data.get(default, "").strip():
                    result[name]["default"] = values[default]
        return result
