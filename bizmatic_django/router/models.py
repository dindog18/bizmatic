"""Human routing configuration, execution history, and destination decisions."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class LLMRunStatus(models.TextChoices):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RoutingDestination(models.Model):
    """One possible destination, such as an AP supplier sales invoice."""

    is_deleted = models.BooleanField(default=False, editable=False)
    destination_no = models.AutoField(primary_key=True)
    name = models.CharField(max_length=160)
    module_name = models.CharField(
        max_length=100, help_text="Django app name, for example accounts_payable.",
    )
    target_model = models.CharField(
        max_length=100, help_text="Model name, for example SupplierSalesInvoice.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module_name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["module_name", "target_model"], condition=models.Q(is_deleted=False), name="router_destination_uq",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.module_name}.{self.target_model})"


class RoutingRule(models.Model):
    """Human-written guidance for when a document belongs at a destination.

    Several active rules may match the same document, including rules for
    different modules. A rule describes a match; it does not stop other matches.
    """

    encoder_connection = models.ForeignKey("encoder.MCPConnection", null=True, blank=True, on_delete=models.PROTECT)
    encoder_tool = models.CharField(max_length=200, blank=True)
    rule_no = models.AutoField(primary_key=True)
    name = models.CharField(max_length=160)
    destination = models.ForeignKey(
        RoutingDestination, on_delete=models.PROTECT, related_name="rules",
    )
    document_type = models.CharField(
        max_length=100, blank=True,
        help_text="Business type, such as sales invoice; separate from PDF/image file type.",
    )
    instructions = models.TextField(
        help_text="Describe when to include this destination and when to exclude it.",
    )
    examples = models.TextField(
        blank=True, help_text="Optional examples of documents that should or should not match.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class LLMRoutingLog(models.Model):
    """One LLM attempt for a document; reruns create separate rows.

    Input, prompt, and rule snapshots describe what was actually sent, so later
    edits to extraction text or routing configuration do not change that history.
    A completed attempt can have zero, one, or several destination results.
    """

    routing_log_no = models.AutoField(primary_key=True)
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    source_document = models.ForeignKey(
        "document_extraction.Document", on_delete=models.CASCADE,
        related_name="routing_logs",
    )
    input_text = models.TextField(
        blank=True, help_text="Exact extraction text used for this routing attempt.",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="routing_logs",
    )
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="routing_logs",
    )
    source_review_status = models.CharField(max_length=20, blank=True)
    confirmed_unapproved = models.BooleanField(default=False)
    source_revision = models.CharField(max_length=40, blank=True)
    prompt_text = models.TextField(blank=True, help_text="Exact routing prompt used for this attempt.")
    rules_snapshot = models.JSONField(
        default=list, blank=True,
        help_text="Rules and destination details used for this attempt, copied before the LLM call.",
    )
    provider = models.CharField(max_length=100, null=True, blank=True)
    model_name = models.CharField(max_length=150, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=LLMRunStatus.choices, default=LLMRunStatus.QUEUED,
    )
    response_text = models.TextField(
        null=True, blank=True, help_text="Original LLM response, including any returned JSON.",
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    user_selected_accurate = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_document"],
                condition=models.Q(status__in=["queued", "processing"]),
                name="router_one_active_document",
            ),
            models.UniqueConstraint(
                fields=["request_id", "source_document"], name="router_request_document_uq",
            ),
        ]

    def __str__(self):
        return f"Document #{self.source_document_id} - routing #{self.routing_log_no}"


class DocumentRoute(models.Model):
    """One proposed destination for one routing attempt, reviewed independently.

    The source document is available through routing_log.source_document.
    LLM matches start accounting extraction while human review stays pending.
    Approval of a pending or failed route also starts its accounting extraction.
    """

    encoder_config = models.JSONField(default=dict, blank=True)
    route_no = models.AutoField(primary_key=True)
    routing_log = models.ForeignKey(
        LLMRoutingLog, on_delete=models.CASCADE, related_name="routes",
    )
    destination = models.ForeignKey(
        RoutingDestination, on_delete=models.PROTECT, related_name="routes",
    )
    processing_status = models.CharField(max_length=20, default="pending", choices=[
        ("pending", "Pending"), ("processing", "Processing"),
        ("completed", "Completed"), ("failed", "Failed"),
    ])
    processing_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    reason = models.TextField(blank=True, help_text="Why this document belongs at this destination.")
    confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
        help_text="Optional LLM confidence from 0 to 1; this is not human approval.",
    )
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING,
    )
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["routing_log", "destination"], name="router_log_destination_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | (models.Q(confidence__gte=0) & models.Q(confidence__lte=1)),
                name="router_confidence_range",
            ),
        ]

    def __str__(self):
        return f"Routing #{self.routing_log_id} - {self.destination}"
