"""Simple Django models for AP document matching and payment allocation."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q

from document_extraction.models import LLMRunStatus

from . import services


class Supplier(models.Model):
    """Supplier identity, contact information, and payment terms."""

    supplier_no = models.AutoField(primary_key=True)
    supplier_code = models.CharField(max_length=50, unique=True)
    supplier_name = models.CharField(max_length=255)
    tax_identification_no = models.CharField(max_length=30, blank=True)
    billing_address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    payment_terms_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    llm_context = models.TextField(blank=True)

    def __str__(self):
        return f"{self.supplier_code} - {self.supplier_name}"

    class Meta:
        ordering = ["supplier_name"]
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"


class CompanyPurchaseOrder(models.Model):
    """Company order sent to a supplier. Its lines describe the agreed quantities and prices."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["CompanyPurchaseOrderLine"]
        supplier_id: int | None

    class Status:
        DRAFT = "draft"
        OPEN = "open"
        CANCELLED = "cancelled"
        CLOSED = "closed"
        choices = [(DRAFT, "Draft"), (OPEN, "Open"), (CANCELLED, "Cancelled"), (CLOSED, "Closed")]

    company_purchase_order = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        "Supplier", on_delete=models.PROTECT, related_name="purchase_orders"
    )
    po_reference_no = models.CharField(max_length=100, unique=True)
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    subtotal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    other_charges = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_purchase_orders",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_purchase_orders",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    purchase_order_metadata = models.TextField(blank=True)
    purchase_order_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    def __str__(self):
        return f"{self.po_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-order_date"]
        verbose_name = "Company Purchase Order"
        verbose_name_plural = "Company Purchase Orders"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_po_source_record_uq",
            )
        ]


class SupplierDeliveryReceipt(models.Model):
    """Goods received from the supplier. Accepted quantities are recorded on its lines."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["SupplierDeliveryReceiptLine"]
        supplier_id: int | None
        receiving_evidence_id: int | None

    class Status:
        PENDING = "pending"
        PARTIAL = "partial"
        ACCEPTED = "accepted"
        REJECTED = "rejected"
        choices = [
            (PENDING, "Pending"),
            (PARTIAL, "Partial"),
            (ACCEPTED, "Accepted"),
            (REJECTED, "Rejected"),
        ]

    supplier_delivery_receipt_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="delivery_receipts"
    )
    dr_reference_no = models.CharField(max_length=100, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    received_by = models.CharField(max_length=255, blank=True)
    receiving_evidence = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_receiving_evidence",
    )
    delivery_location = models.CharField(max_length=255, blank=True)
    receipt_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    has_discrepancy = models.BooleanField(default=False)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_delivery_receipts",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_delivery_receipts",
    )
    # Optional receiving notes from import; matching uses the receipt line quantities.
    received_items = models.JSONField(default=list, blank=True)
    # Optional document notes and context; matching uses the structured fields and lines.
    delivery_receipt_metadata = models.TextField(blank=True)
    delivery_receipt_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    def __str__(self):
        return f"{self.dr_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-delivery_date"]
        verbose_name = "Supplier Delivery Receipt"
        verbose_name_plural = "Supplier Delivery Receipts"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_dr_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["supplier", "dr_reference_no"], name="unique_supplier_dr_reference"
            ),
        ]


class SupplierSalesInvoice(models.Model):
    """Supplier bill payable by the company. Allocations determine its outstanding balance."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["SupplierSalesInvoiceLine"]
        payment_allocations: models.Manager["PaymentAllocation"]
        supplier_id: int | None

    class InvoiceStatus:
        PENDING = "pending"
        POSTED = "posted"
        DISPUTED = "disputed"
        VOID = "void"
        choices = [(PENDING, "Pending"), (POSTED, "Posted"), (DISPUTED, "Disputed"), (VOID, "Void")]

    class PaymentStatus:
        UNPAID = "unpaid"
        PARTIALLY_PAID = "partially_paid"
        PAID = "paid"
        choices = [(UNPAID, "Unpaid"), (PARTIALLY_PAID, "Partially paid"), (PAID, "Paid")]

    supplier_sales_invoice_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_invoices"
    )
    invoice_reference_no = models.CharField(max_length=100, null=True, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        blank=True,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    subtotal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    other_charges = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    invoice_status = models.CharField(
        max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.PENDING
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    notes = models.TextField(blank=True)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_sales_invoices",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_sales_invoices",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    invoice_metadata = models.TextField(blank=True)
    invoice_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        services.validate_invoice_allocations(self)

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    @property
    def settled_amount(self) -> Decimal:
        return services.settled_amount(self)

    @property
    def outstanding_balance(self) -> Decimal:
        return max(Decimal("0"), self.total_amount - self.settled_amount)

    def refresh_payment_status(self):
        # Keep the stored payment status in step with cleared allocations.
        settled = self.settled_amount
        if settled >= self.total_amount > Decimal("0"):
            status = "paid"
        elif settled > Decimal("0"):
            status = "partially_paid"
        else:
            status = "unpaid"
        type(self).objects.filter(pk=self.pk).update(payment_status=status)
        self.payment_status = status

    def __str__(self):
        return f"{self.invoice_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-invoice_date"]
        verbose_name = "Supplier Sales Invoice"
        verbose_name_plural = "Supplier Sales Invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_invoice_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["supplier", "invoice_reference_no"],
                name="unique_supplier_invoice_reference",
            ),
        ]


class CompanyPayment(models.Model):
    """Money paid to a supplier. One payment may settle several invoices."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        invoice_allocations: models.Manager["PaymentAllocation"]
        supplier_id: int | None
        proof_of_payment_id: int | None

    class Status:
        PENDING = "pending"
        CLEARED = "cleared"
        REVERSED = "reversed"
        choices = [(PENDING, "Pending"), (CLEARED, "Cleared"), (REVERSED, "Reversed")]

    company_payment_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    payment_reference_no = models.CharField(max_length=100, null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    posting_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    bank_reference_no = models.CharField(max_length=100, blank=True)
    currency = models.CharField(
        max_length=3,
        blank=True,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    amount_paid = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    withholding_tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_taken = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    payment_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    cleared_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True)
    proof_of_payment = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_payment_proofs",
    )
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_payments",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_payments",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    payment_metadata = models.TextField(blank=True)
    payment_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        services.validate_payment_amounts(self)

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            for allocation in self.invoice_allocations.select_related("invoice"):
                allocation.invoice.refresh_payment_status()
            return result

    @property
    def unallocated_amount(self) -> Decimal:
        return services.unallocated_cash(self)

    def __str__(self):
        return f"{self.payment_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-payment_date"]
        verbose_name = "Company Payment"
        verbose_name_plural = "Company Payments"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_payment_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["supplier", "payment_reference_no"],
                name="unique_supplier_payment_reference",
            ),
        ]


class Transaction(models.Model):
    """One AP reconciliation case grouping orders, receipts, and invoices for the same supplier and currency."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        supplier_id: int | None
        line_matches: models.Manager["DocumentMatch"]

    class Status:
        PENDING = "pending"
        MATCHED = "matched"
        PARTIAL = "partial"
        EXCEPTION = "exception"
        choices = [
            (PENDING, "Pending"),
            (MATCHED, "Matched"),
            (PARTIAL, "Partial"),
            (EXCEPTION, "Exception"),
        ]

    transaction_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    transaction_date = models.DateField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        blank=True,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    reconciliation_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    total_discrepancy_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    # A case can include split deliveries, multiple orders, and multiple invoices.
    purchase_orders = models.ManyToManyField(
        CompanyPurchaseOrder, blank=True, related_name="reconciliation_cases"
    )
    delivery_receipts = models.ManyToManyField(
        SupplierDeliveryReceipt, blank=True, related_name="reconciliation_cases"
    )
    sales_invoices = models.ManyToManyField(
        SupplierSalesInvoice, blank=True, related_name="reconciliation_cases"
    )

    def calculate_reconciliation(self) -> tuple[str, Decimal]:
        return services.calculate_reconciliation(self)

    def refresh_reconciliation_status(self):
        # Store the result calculated from current documents and line matches.
        if not self.pk:
            return
        status, discrepancy = self.calculate_reconciliation()
        type(self).objects.filter(pk=self.pk).update(
            reconciliation_status=status, total_discrepancy_amount=discrepancy
        )
        self.reconciliation_status = status
        self.total_discrepancy_amount = discrepancy

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_case(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"AP transaction {self.transaction_no} - {self.supplier}"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AP Transaction"
        verbose_name_plural = "AP Transactions"


class CompanyPurchaseOrderLine(models.Model):
    """One ordered item: its quantity, unit price, discount, tax, and total."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        matches: models.Manager["DocumentMatch"]
        purchase_order_id: int | None

    # A stable line number identifies the item within its parent document.
    line_no = models.PositiveIntegerField()
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30, blank=True)
    quantity_ordered = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_price = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    line_total = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    purchase_order = models.ForeignKey(
        CompanyPurchaseOrder, on_delete=models.PROTECT, related_name="lines"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_line(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self.purchase_order)
            return result

    def delete(self, *args, **kwargs):
        document = self.purchase_order
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            services.refresh_document_cases(document)
            return result

    def __str__(self):
        return f"{self.purchase_order} line {self.line_no}"

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "line_no"], name="ap_po_line_number_uq"
            )
        ]


class SupplierDeliveryReceiptLine(models.Model):
    """One delivered item with stated, received, accepted, and rejected quantities."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        matches: models.Manager["DocumentMatch"]
        delivery_receipt_id: int | None

    # A stable line number identifies the item within its parent document.
    line_no = models.PositiveIntegerField()
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30, blank=True)
    # Keep the document claim separate from what was actually received and accepted.
    quantity_stated = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_received = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_accepted = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_rejected = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    delivery_receipt = models.ForeignKey(
        SupplierDeliveryReceipt, on_delete=models.PROTECT, related_name="lines"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_line(self)
        if self.quantity_accepted + self.quantity_rejected > self.quantity_received:
            raise ValidationError("Accepted and rejected quantities exceed the received quantity.")

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self.delivery_receipt)
            return result

    def delete(self, *args, **kwargs):
        document = self.delivery_receipt
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            services.refresh_document_cases(document)
            return result

    def __str__(self):
        return f"{self.delivery_receipt} line {self.line_no}"

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery_receipt", "line_no"], name="ap_dr_line_number_uq"
            )
        ]


class SupplierSalesInvoiceLine(models.Model):
    """One billed item whose quantity and price are compared with order and receipt lines."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        matches: models.Manager["DocumentMatch"]
        invoice_id: int | None

    # A stable line number identifies the item within its parent document.
    line_no = models.PositiveIntegerField()
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30, blank=True)
    quantity_invoiced = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_price = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    line_total = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    invoice = models.ForeignKey(
        SupplierSalesInvoice, on_delete=models.PROTECT, related_name="lines"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_line(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self.invoice)
            return result

    def delete(self, *args, **kwargs):
        document = self.invoice
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            services.refresh_document_cases(document)
            return result

    def __str__(self):
        return f"{self.invoice} line {self.line_no}"

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="ap_invoice_line_number_uq")
        ]


class DocumentMatch(models.Model):
    """Links a portion of an invoice line to an order line and an accepted receipt line."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        transaction_id: int | None
        purchase_order_line_id: int | None
        delivery_receipt_line_id: int | None
        invoice_line_id: int | None

    class Status:
        PENDING = "pending"
        MATCHED = "matched"
        EXCEPTION = "exception"
        choices = [(PENDING, "Pending"), (MATCHED, "Matched"), (EXCEPTION, "Exception")]

    # A partial quantity allows one order or receipt line to cover several invoice lines.
    matched_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    match_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    transaction = models.ForeignKey(
        Transaction, on_delete=models.PROTECT, related_name="line_matches"
    )
    purchase_order_line = models.ForeignKey(
        CompanyPurchaseOrderLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches",
    )
    delivery_receipt_line = models.ForeignKey(
        SupplierDeliveryReceiptLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches",
    )
    invoice_line = models.ForeignKey(
        SupplierSalesInvoiceLine, on_delete=models.PROTECT, related_name="matches"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_match(self)

    def save(self, *args, **kwargs):
        # Lock the affected rows so concurrent matches or allocations cannot reuse them.
        with transaction.atomic():
            if self.invoice_line_id:
                SupplierSalesInvoiceLine.objects.select_for_update().get(pk=self.invoice_line_id)
            if self.purchase_order_line_id:
                CompanyPurchaseOrderLine.objects.select_for_update().get(
                    pk=self.purchase_order_line_id
                )
            if self.delivery_receipt_line_id:
                SupplierDeliveryReceiptLine.objects.select_for_update().get(
                    pk=self.delivery_receipt_line_id
                )
            self.full_clean()
            result = super().save(*args, **kwargs)
            self.transaction.refresh_reconciliation_status()
            return result

    def delete(self, *args, **kwargs):
        case = self.transaction
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            case.refresh_reconciliation_status()
            return result

    def __str__(self):
        return f"AP match {self.pk} for invoice line {self.invoice_line_id}"

    class Meta:
        ordering = ["-created_at"]


class PaymentAllocation(models.Model):
    """Applies cash, withholding tax, and discounts from one payment to one invoice."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        payment_id: int | None
        invoice_id: int | None
    # Cash, withholding tax, and discounts together settle the invoice amount.
    cash_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    withholding_tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    payment = models.ForeignKey(
        CompanyPayment, on_delete=models.PROTECT, related_name="invoice_allocations"
    )
    invoice = models.ForeignKey(
        SupplierSalesInvoice, on_delete=models.PROTECT, related_name="payment_allocations"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_allocation(self)

    def save(self, *args, **kwargs):
        # Lock the affected rows so concurrent matches or allocations cannot reuse them.
        with transaction.atomic():
            if self.payment_id:
                CompanyPayment.objects.select_for_update().get(pk=self.payment_id)
            if self.invoice_id:
                SupplierSalesInvoice.objects.select_for_update().get(pk=self.invoice_id)
            old_invoice_id = None
            if self.pk:
                old_invoice_id = (
                    type(self)
                    .objects.filter(pk=self.pk)
                    .values_list("invoice_id", flat=True)
                    .first()
                )
            self.full_clean()
            result = super().save(*args, **kwargs)
            self.invoice.refresh_payment_status()
            if old_invoice_id and old_invoice_id != self.invoice_id:
                SupplierSalesInvoice.objects.get(pk=old_invoice_id).refresh_payment_status()
            return result

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            invoice.refresh_payment_status()
            return result

    def __str__(self):
        return f"{self.payment} → {self.invoice}"

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["payment", "invoice"], name="ap_payment_invoice_uq")
        ]


class ExtractionConfiguration(models.Model):
    """User-reviewed instructions for entering one kind of accounting record.

    A profile describes either database mapping or document extraction, scoped
    to the module or an existing Supplier. It never imports or encodes a record
    by itself. The frontend currently previews these fields in browser storage;
    persistence, provider calls, validation services, and migrations are deferred.
    Existing per-record context/provenance fields retain their current meaning.
    """

    class TargetEntity(models.TextChoices):
        SUPPLIER = "supplier", "Supplier"
        PURCHASE_ORDER = "purchase_order", "Purchase order"
        DELIVERY_RECEIPT = "delivery_receipt", "Delivery receipt"
        SALES_INVOICE = "sales_invoice", "Sales invoice"
        PAYMENT = "payment", "Payment"

    class SourceType(models.TextChoices):
        DATABASE = "database", "Database extraction"
        DOCUMENT = "document", "Document extraction"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted by user"

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    target_entity = models.CharField(max_length=30, choices=TargetEntity.choices)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    supplier = models.ForeignKey(
        "Supplier", on_delete=models.PROTECT, null=True, blank=True,
        related_name="extraction_configurations",
        help_text="Blank applies module-wide; otherwise use this account's layout or mapping.",
    )

    # Schema metadata identifies external fields; no credentials or SQL are stored.
    database_source = models.ForeignKey(
        "db_extraction.DatabaseSource", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_extraction_configurations",
    )
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_header_configurations",
    )
    line_source_table = models.ForeignKey(
        "db_extraction.DatabaseTable", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_line_configurations",
    )
    source_schema_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Connection/table labels and inspected columns at configuration time; not business rows.",
    )
    source_key_fields = models.JSONField(
        default=list, blank=True, help_text="External header key column names, including composite keys.",
    )
    # {target_field: {source: column_name, transform: name, default: value}}
    field_mappings = models.JSONField(default=dict, blank=True)
    line_item_mappings = models.JSONField(default=dict, blank=True)
    # [{header_column: 'id', line_column: 'invoice_id'}]
    line_join_fields = models.JSONField(default=list, blank=True)
    # Resolve external account codes to local records instead of copying raw IDs.
    relation_lookups = models.JSONField(
        default=dict, blank=True,
        help_text="Target relation, matching account field, and missing-account review policy.",
    )

    document_type = models.CharField(max_length=100, blank=True)
    extraction_context = models.TextField(blank=True)
    field_instructions = models.JSONField(
        default=dict, blank=True, help_text="Instructions keyed by destination model field name.",
    )
    line_field_instructions = models.JSONField(
        default=dict, blank=True, help_text="Line-field guidance, separate from identically named header fields.",
    )
    line_item_context = models.TextField(blank=True)
    sample_text = models.TextField(blank=True, help_text="Optional user-supplied example for assisted configuration.")
    # Dates, decimal separators, default currency, required fields and duplicates.
    encoding_rules = models.JSONField(default=dict, blank=True)

    # Assistant output is a proposal. Only a later explicit user submission may
    # set submitted_at/by and capture the exact reviewed configuration snapshot.
    assistant_messages = models.JSONField(default=list, blank=True)
    assistant_proposal = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    submitted_snapshot = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ap_submitted_extraction_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_entity", "name", "pk"]
        verbose_name = "AP extraction configuration"
        verbose_name_plural = "AP extraction configurations"

    def __str__(self):
        return f"{self.name} ({self.get_target_entity_display()} · {self.get_source_type_display()})"


class LLMExtractionLog(models.Model):
    """One accounting LLM attempt, including its original input and output.

    Existing source_llm_log fields still identify document-extraction evidence.
    This history covers accounting extraction and configuration assistance.
    Recording attempts and calling providers require a future backend; the UI
    currently stores explicitly simulated attempts in this browser tab only.
    """

    class Purpose(models.TextChoices):
        EXTRACTION = "extraction", "Record extraction"
        CONFIGURATION = "configuration", "Configuration assistance"

    llm_log_no = models.AutoField(primary_key=True)
    configuration = models.ForeignKey(
        "ExtractionConfiguration", on_delete=models.PROTECT, null=True,
        blank=True, related_name="llm_logs",
    )
    configuration_revision = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
    )
    target_entity = models.CharField(max_length=30, choices=ExtractionConfiguration.TargetEntity.choices)
    source_type = models.CharField(max_length=20, choices=ExtractionConfiguration.SourceType.choices)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.EXTRACTION)
    # Optional destination links allow attempts before a record exists.
    supplier = models.ForeignKey(
        "Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    purchase_order = models.ForeignKey(
        "CompanyPurchaseOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    delivery_receipt = models.ForeignKey(
        "SupplierDeliveryReceipt", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    sales_invoice = models.ForeignKey(
        "SupplierSalesInvoice", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    payment = models.ForeignKey(
        "CompanyPayment", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    fk_document_no = models.ForeignKey(
        "document_extraction.Document", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_llm_logs",
    )
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog", on_delete=models.PROTECT,
        null=True, blank=True, related_name="ap_accounting_logs",
    )
    provider = models.CharField(max_length=100, null=True, blank=True)
    model_name = models.CharField(max_length=150, null=True, blank=True)
    status = models.CharField(max_length=20, choices=LLMRunStatus.choices, default=LLMRunStatus.QUEUED)
    # Snapshots preserve the context used by this attempt, even if the draft changes.
    configuration_snapshot = models.JSONField(default=dict, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    markdown_text = models.TextField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    is_simulated = models.BooleanField(default=False)
    # Accuracy review is independent of applying changes or submitting a profile.
    user_selected_accurate = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ap_reviewed_llm_logs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-llm_log_no"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="ap_llm_status_created"),
            models.Index(fields=["configuration", "-created_at"], name="ap_llm_config_created"),
        ]
        verbose_name = "AP LLM extraction log"

    def __str__(self):
        return f"AP LLM #{self.llm_log_no} · {self.get_status_display()}"
