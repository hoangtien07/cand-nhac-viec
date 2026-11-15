import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class RecordStatus(models.TextChoices):
    OPEN = "OPEN", "Đang xử lý"
    DONE = "DONE", "Đã hoàn thành"


class WorkRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="records")
    reference_no = models.CharField("Số hiệu gốc", max_length=64)
    reference_no_normalized = models.CharField(max_length=64, db_index=True)
    owner_department = models.ForeignKey(
        "organization.Department",
        verbose_name="Phòng chủ trì",
        on_delete=models.PROTECT,
        related_name="records",
    )
    assigner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    due_at = models.DateTimeField("Hạn xử lý")
    status = models.CharField(max_length=10, choices=RecordStatus.choices, default=RecordStatus.OPEN)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        ordering = ["due_at"]
        indexes = [
            models.Index(fields=["unit", "status", "due_at"]),
            models.Index(fields=["owner_department", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["OPEN", "DONE"]), name="record_status_valid"),
            models.CheckConstraint(
                condition=(
                    Q(status="OPEN", completed_at__isnull=True, completed_by__isnull=True)
                    | Q(status="DONE", completed_at__isnull=False, completed_by__isnull=False)
                ),
                name="record_completion_consistent",
            ),
        ]

    def __str__(self):
        return self.reference_no

    @property
    def is_open(self):
        return self.status == RecordStatus.OPEN


class RecordAssignee(models.Model):
    record = models.ForeignKey(WorkRecord, on_delete=models.PROTECT, related_name="assignees")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["record", "user"], name="uniq_assignee_per_record")]
        indexes = [models.Index(fields=["user", "is_active"])]


class RecordWatcher(models.Model):
    record = models.ForeignKey(WorkRecord, on_delete=models.PROTECT, related_name="watchers")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="watching")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["record", "user"], name="uniq_watcher_per_record")]
        indexes = [models.Index(fields=["user", "is_active"])]


class ResultReference(models.Model):
    """Immutable in MVP (CONTEXT H03). A PostgreSQL trigger rejects UPDATE/DELETE (migration 0002)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(WorkRecord, on_delete=models.PROTECT, related_name="results")
    code = models.CharField("Số hiệu kết quả", max_length=64)
    normalized_code = models.CharField(max_length=64)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        ordering = ["submitted_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["record", "normalized_code"], name="uniq_result_code_per_record")
        ]
