"""Post-routing preparation and explicitly approved MCP execution history."""
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from db_extraction.fields import EncryptedPasswordField


class MCPConnection(models.Model):
    name = models.CharField(max_length=160, unique=True)
    launch_profile = models.CharField(max_length=100, blank=True, help_text="Trusted stdio launch profile configured on the Django server.")
    transport = models.CharField(max_length=20, choices=[("stdio", "STDIO"), ("streamable_http", "Streamable HTTP")], default="stdio")
    server_url = models.URLField(max_length=2000, blank=True)
    bearer_token_env_var = models.CharField(max_length=200, blank=True)
    http_headers = EncryptedPasswordField(blank=True, default="")
    env_http_headers = models.JSONField(default=dict, blank=True)
    command = models.CharField(max_length=1000, blank=True)
    arguments = models.JSONField(default=list, blank=True)
    working_directory = models.CharField(max_length=1000, blank=True)
    environment_passthrough = models.JSONField(default=list, blank=True)
    environment = EncryptedPasswordField(blank=True, default="")
    enabled = models.BooleanField(default=True)
    timeout_seconds = models.PositiveIntegerField(default=30, validators=[MinValueValidator(1), MaxValueValidator(300)])
    approved_tools = models.JSONField(default=list, blank=True)
    tools = models.JSONField(default=list, blank=True)
    discovery_error = models.TextField(blank=True)
    discovered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EncoderMapping(models.Model):
    connection = models.ForeignKey(MCPConnection, on_delete=models.PROTECT, related_name="mappings")
    tool_name = models.CharField(max_length=200)
    field_mappings = models.JSONField(default=dict, blank=True)
    idempotency_field = models.CharField(max_length=200, blank=True, help_text="Only set when the server documents this string parameter as an idempotency key.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "tool_name"], name="encoder_mapping_tool_uq")]


class EncoderJob(models.Model):
    cycle = models.PositiveIntegerField(default=1)
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        MAPPING = "mapping", "Mapping"
        NEEDS_REVIEW = "needs_review", "Needs review"
        READY = "ready", "Ready"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # The route owns the document and exact extraction references and text snapshot.
    route = models.OneToOneField("router.DocumentRoute", on_delete=models.PROTECT, related_name="encoder_job")
    connection = models.ForeignKey(MCPConnection, null=True, blank=True, on_delete=models.PROTECT)
    tool_name = models.CharField(max_length=200, blank=True)
    tool_schema = models.JSONField(default=dict, blank=True)
    field_mappings = models.JSONField(default=dict, blank=True)
    prepared_payload = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    idempotency_field = models.CharField(max_length=200, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Encoder job"

    @property
    def document(self):
        return self.route.routing_log.source_document


class EncoderExecution(models.Model):
    cycle = models.PositiveIntegerField(default=1)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    job = models.ForeignKey(EncoderJob, on_delete=models.PROTECT, related_name="executions")
    connection = models.ForeignKey(MCPConnection, on_delete=models.PROTECT)
    tool_name = models.CharField(max_length=200)
    tool_schema = models.JSONField(default=dict)
    connection_snapshot = models.JSONField(default=dict)
    payload = models.JSONField(default=dict)
    response = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="processing", choices=[("processing", "Processing"), ("completed", "Completed"), ("failed", "Failed before invocation"), ("unknown", "Verify external outcome")])
    error_message = models.TextField(blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-confirmed_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["job"], condition=models.Q(status="processing"), name="encoder_one_active_execution")]


class EncoderChatMessage(models.Model):
    cycle = models.PositiveIntegerField(default=1)
    provider = models.CharField(max_length=100, blank=True)
    model_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, blank=True, default="", choices=[("", "Not recorded"), ("processing", "Processing"), ("completed", "Completed"), ("failed", "Failed")])
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)

    job = models.ForeignKey(EncoderJob, on_delete=models.CASCADE, related_name="chat_messages")
    role = models.CharField(max_length=20, choices=[("user", "User"), ("assistant", "Assistant"), ("routing", "Routing preparation")])
    content = models.TextField()
    proposal = models.JSONField(default=dict, blank=True)
    base_revision = models.CharField(max_length=50, blank=True)
    decision = models.CharField(max_length=20, default="pending", choices=[("pending", "Pending"), ("accepted", "Accepted"), ("prepared", "Prepared automatically"), ("rejected", "Rejected")])
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class EncoderReset(models.Model):
    job = models.ForeignKey(EncoderJob, on_delete=models.PROTECT, related_name="resets")
    cycle = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
