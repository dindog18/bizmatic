"""PostgreSQL connection profiles and schema snapshots; never source table rows."""

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .fields import EncryptedPasswordField


class DatabaseSource(models.Model):
    """One independently configured PostgreSQL database, stored in the application database."""

    if TYPE_CHECKING:
        extraction_runs: models.Manager["ExtractionRun"]

    class SSLMode:
        """String constants and explicit Django field choices for IDE compatibility."""

        DISABLE = "disable"
        ALLOW = "allow"
        PREFER = "prefer"
        REQUIRE = "require"
        VERIFY_CA = "verify-ca"
        VERIFY_FULL = "verify-full"

        choices = [
            (DISABLE, "Disable"),
            (ALLOW, "Allow"),
            (PREFER, "Prefer"),
            (REQUIRE, "Require"),
            (VERIFY_CA, "Verify CA"),
            (VERIFY_FULL, "Verify full"),
        ]

    name = models.CharField(max_length=255, unique=True)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=5432, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    database_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    password = EncryptedPasswordField(
        blank=True,
        help_text="Encrypted in the application database. Use a dedicated metadata/read-only account.",
    )
    ssl_mode = models.CharField(max_length=11, choices=SSLMode.choices, default=SSLMode.PREFER)
    ssl_root_cert = models.CharField(max_length=1000, blank=True, help_text="CA certificate path on the application server.")
    connect_timeout = models.PositiveIntegerField(default=10, validators=[MinValueValidator(1)])
    enabled = models.BooleanField(default=True)
    included_schemas = models.JSONField(default=list, blank=True, help_text="Schema names to inspect; empty means all non-system schemas.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        super().clean()
        if not isinstance(self.included_schemas, list) or any(
            not isinstance(name, str) or not name.strip() for name in self.included_schemas
        ):
            raise ValidationError({"included_schemas": "Enter a list of nonempty schema names."})

    def __str__(self):
        return self.name


class ExtractionRun(models.Model):
    """One metadata snapshot and its outcome, independent of previous snapshots."""

    if TYPE_CHECKING:
        schemas: models.Manager["DatabaseSchema"]

    class Status:
        """String constants and explicit Django field choices for IDE compatibility."""

        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

        choices = [
            (QUEUED, "Queued"),
            (RUNNING, "Running"),
            (COMPLETED, "Completed"),
            (FAILED, "Failed"),
        ]

    source = models.ForeignKey(DatabaseSource, on_delete=models.PROTECT, related_name="extraction_runs")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Retain the inspected database identity if the source profile changes later.
    database_name = models.CharField(max_length=255, blank=True)
    server_version = models.CharField(max_length=100, blank=True)
    extractor_version = models.CharField(max_length=50, blank=True)
    included_schemas = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True, help_text="Sanitized error only; never include credentials or connection strings.")

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["source", "status", "-created_at"])]

    def __str__(self):
        return f"{self.source} — run {self.pk} ({self.status})"


class DatabaseSchema(models.Model):
    """A PostgreSQL namespace captured in one extraction run."""

    run = models.ForeignKey(ExtractionRun, on_delete=models.CASCADE, related_name="schemas")
    name = models.CharField(max_length=255)
    owner = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["run", "name"], name="dbext_schema_run_name_uq")]

    def __str__(self):
        return self.name


class DatabaseTable(models.Model):
    """A relation definition; no table contents or sample rows are stored."""

    if TYPE_CHECKING:
        columns: models.Manager["DatabaseColumn"]
        constraints: models.Manager["DatabaseConstraint"]
        indexes: models.Manager["DatabaseIndex"]

    class RelationKind:
        """String constants and explicit Django field choices for IDE compatibility."""

        TABLE = "table"
        PARTITIONED = "partitioned"
        FOREIGN = "foreign"
        VIEW = "view"
        MATERIALIZED_VIEW = "materialized_view"

        choices = [
            (TABLE, "Table"),
            (PARTITIONED, "Partitioned table"),
            (FOREIGN, "Foreign table"),
            (VIEW, "View"),
            (MATERIALIZED_VIEW, "Materialized view"),
        ]

    schema = models.ForeignKey(DatabaseSchema, on_delete=models.CASCADE, related_name="tables")
    name = models.CharField(max_length=255)
    relation_kind = models.CharField(max_length=17, choices=RelationKind.choices, default=RelationKind.TABLE)
    owner = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    view_definition = models.TextField(blank=True)
    partition_definition = models.TextField(blank=True)
    row_security_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["schema", "name"], name="dbext_table_schema_name_uq")]

    def __str__(self):
        return f"{self.schema.name}.{self.name}"


class DatabaseColumn(models.Model):
    """Column definition, including PostgreSQL types and generated expressions."""

    # Django creates this ID attribute from the ForeignKey at runtime.
    table_id: int | None
    table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE, related_name="columns")
    name = models.CharField(max_length=255)
    ordinal_position = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    formatted_type = models.TextField(help_text="Complete PostgreSQL type, for example numeric(12,2).")
    type_schema = models.CharField(max_length=255, blank=True)
    type_name = models.CharField(max_length=255, blank=True)
    domain_schema = models.CharField(max_length=255, blank=True)
    domain_name = models.CharField(max_length=255, blank=True)
    nullable = models.BooleanField(default=True)
    default_expression = models.TextField(blank=True)
    character_maximum_length = models.PositiveIntegerField(null=True, blank=True)
    numeric_precision = models.PositiveIntegerField(null=True, blank=True)
    numeric_scale = models.IntegerField(null=True, blank=True)
    identity_generation = models.CharField(max_length=10, blank=True, choices=[("ALWAYS", "Always"), ("BY DEFAULT", "By default")])
    generated_expression = models.TextField(blank=True)
    collation_schema = models.CharField(max_length=255, blank=True)
    collation_name = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["ordinal_position"]
        constraints = [
            models.UniqueConstraint(fields=["table", "name"], name="dbext_column_table_name_uq"),
            models.UniqueConstraint(fields=["table", "ordinal_position"], name="dbext_column_table_pos_uq"),
        ]

    def __str__(self):
        return f"{self.table}.{self.name}"


class DatabaseConstraint(models.Model):
    """Table constraint with its original definition and optional FK target."""

    if TYPE_CHECKING:
        columns: models.Manager["ConstraintColumn"]

    class ConstraintType:
        """String constants and explicit Django field choices for IDE compatibility."""

        PRIMARY_KEY = "primary_key"
        FOREIGN_KEY = "foreign_key"
        UNIQUE = "unique"
        CHECK = "check"
        EXCLUSION = "exclusion"
        NOT_NULL = "not_null"

        choices = [
            (PRIMARY_KEY, "Primary key"),
            (FOREIGN_KEY, "Foreign key"),
            (UNIQUE, "Unique"),
            (CHECK, "Check"),
            (EXCLUSION, "Exclusion"),
            (NOT_NULL, "Not null"),
        ]

    # Django creates this ID attribute from the ForeignKey at runtime.
    table_id: int | None
    table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE, related_name="constraints")
    name = models.CharField(max_length=255)
    constraint_type = models.CharField(max_length=11, choices=ConstraintType.choices)
    definition = models.TextField()
    # Names retain FK targets even when their schema is outside the extraction scope.
    referenced_schema = models.CharField(max_length=255, blank=True)
    referenced_table = models.CharField(max_length=255, blank=True)
    update_action = models.CharField(max_length=20, blank=True)
    delete_action = models.CharField(max_length=20, blank=True)
    match_type = models.CharField(max_length=20, blank=True)
    is_deferrable = models.BooleanField(default=False)
    initially_deferred = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["table", "name"], name="dbext_constraint_table_name_uq"),
        ]

    def __str__(self):
        return f"{self.table}: {self.name}"


class ConstraintColumn(models.Model):
    """Ordered key membership and corresponding target column for composite FKs."""

    # Annotations describe Django-generated attributes without replacing their descriptors.
    constraint_id: int | None
    column_id: int | None

    constraint = models.ForeignKey(DatabaseConstraint, on_delete=models.CASCADE, related_name="columns")
    column = models.ForeignKey(DatabaseColumn, on_delete=models.CASCADE, related_name="constraint_memberships")
    position = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    referenced_column_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["constraint", "position"], name="dbext_constraint_position_uq")]

    def clean(self):
        super().clean()
        if self.constraint_id and self.column_id and self.constraint.table_id != self.column.table_id:
            raise ValidationError({"column": "The column must belong to the constraint's table."})


class DatabaseIndex(models.Model):
    """Index metadata; definition retains expressions, key order, and INCLUDE columns."""

    table = models.ForeignKey(DatabaseTable, on_delete=models.CASCADE, related_name="indexes")
    name = models.CharField(max_length=255)
    definition = models.TextField()
    access_method = models.CharField(max_length=100, blank=True)
    is_unique = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    is_valid = models.BooleanField(default=True)
    predicate = models.TextField(blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["table", "name"], name="dbext_index_table_name_uq")]

    def __str__(self):
        return f"{self.table}: {self.name}"
