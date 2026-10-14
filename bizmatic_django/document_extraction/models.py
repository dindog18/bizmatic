from django.db import models


# Options
class ProcessingStatus(models.TextChoices):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ReviewStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LLMRunStatus(models.TextChoices):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Main Models

class Batch(models.Model):
    batch_no = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.batch_no)


class Document(models.Model):
    document_no = models.AutoField(primary_key=True)
    fk_batch_no = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    file_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=150, null=True, blank=True)
    document_type = models.CharField(max_length=100)
    storage_path = models.CharField(max_length=1000)
    processing_status = models.CharField(max_length=20, choices=ProcessingStatus.choices,
                                         default=ProcessingStatus.QUEUED)
    review_status = models.CharField(max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.file_name


class LLMExtractionLog(models.Model):
    llm_log_no = models.AutoField(primary_key=True)
    fk_document_no = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="llm_logs")
    provider = models.CharField(max_length=100, null=True, blank=True)
    model_name = models.CharField(max_length=150, null=True, blank=True)
    status = models.CharField(max_length=20, choices=LLMRunStatus.choices, default=LLMRunStatus.QUEUED)
    markdown_text = models.TextField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    user_selected_accurate = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fk_document_no} - {self.llm_log_no}"


class DocExtractionLog(models.Model):
    doc_log_no = models.AutoField(primary_key=True)
    fk_document_no = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="text_logs")
    markdown_text = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    user_selected_accurate = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fk_document_no} - {self.doc_log_no}"
