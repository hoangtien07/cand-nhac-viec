import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class RecordStatus(models.TextChoices):
    OPEN = "OPEN", "Đang xử lý"
    DONE = "DONE", "Đã hoàn thành"


class TaskKind(models.TextChoices):
    DOCUMENT = "DOCUMENT", "Văn bản"
    OTHER = "OTHER", "Nhiệm vụ khác"


class PeriodicPlanStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Đang áp dụng"
    CLOSED = "CLOSED", "Đã kết thúc"


class PeriodicPlan(models.Model):
    """Văn bản/nhiệm vụ định kỳ: 1 plan → 1..12 WorkRecord con (mỗi kỳ một hạn riêng).

    ADR-005: children keep their own due_at/status/results; stats never count a plan
    as 12 documents. Rows are PROTECTed so a plan cannot be hard-deleted while
    children exist.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(
        "organization.Unit", on_delete=models.PROTECT, related_name="periodic_plans"
    )
    name = models.CharField("Tên văn bản/nhiệm vụ định kỳ", max_length=200)
    task_kind = models.CharField(max_length=10, choices=TaskKind.choices, default=TaskKind.DOCUMENT)
    reference_no = models.CharField("Số hiệu chung (nếu có)", max_length=64, blank=True)
    year = models.PositiveSmallIntegerField("Năm áp dụng")
    owner_department = models.ForeignKey(
        "organization.Department",
        verbose_name="Phòng chủ trì",
        on_delete=models.PROTECT,
        related_name="periodic_plans",
    )
    status = models.CharField(
        max_length=10, choices=PeriodicPlanStatus.choices, default=PeriodicPlanStatus.ACTIVE
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        ordering = ["-year", "name", "id"]
        indexes = [models.Index(fields=["unit", "year"])]

    def __str__(self):
        return f"{self.name} ({self.year})"

    @property
    def period_count(self):
        return self.periods.count()


class WorkRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="records")
    task_kind = models.CharField(max_length=10, choices=TaskKind.choices, default=TaskKind.DOCUMENT)
    title = models.CharField("Tên nhiệm vụ", max_length=200, blank=True)
    task_code = models.CharField("Mã nhiệm vụ nội bộ", max_length=64, blank=True)
    # STT3/WP2: nullable — OTHER tasks may not carry a document reference number.
    reference_no = models.CharField("Số hiệu gốc", max_length=64, blank=True)
    reference_no_normalized = models.CharField(max_length=64, db_index=True, blank=True)
    periodic_plan = models.ForeignKey(
        PeriodicPlan,
        verbose_name="Kế hoạch định kỳ",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="periods",
    )
    period_index = models.PositiveSmallIntegerField(null=True, blank=True)
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
    folder = models.ForeignKey(
        "organization.WorkFolder",
        verbose_name="Nhóm hồ sơ",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="records",
    )
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    archive_reason = models.CharField("Lý do lưu trữ", max_length=300, blank=True)
    description_short = models.CharField("Ghi chú/mô tả ngắn", max_length=200, blank=True)

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
            models.CheckConstraint(
                condition=(
                    Q(archived_at__isnull=True, archived_by__isnull=True)
                    | Q(archived_at__isnull=False, archived_by__isnull=False)
                ),
                name="record_archive_consistent",
            ),
            # period_index only exists on a plan child, always within 1..12.
            models.CheckConstraint(
                condition=(
                    Q(periodic_plan__isnull=True, period_index__isnull=True)
                    | Q(
                        periodic_plan__isnull=False,
                        period_index__gte=1,
                        period_index__lte=12,
                    )
                ),
                name="record_period_consistent",
            ),
            models.UniqueConstraint(
                fields=["periodic_plan", "period_index"],
                condition=Q(periodic_plan__isnull=False),
                name="uniq_period_index_per_plan",
            ),
            models.UniqueConstraint(
                fields=["unit", "task_code"],
                condition=~Q(task_code=""),
                name="uniq_task_code_per_unit",
            ),
        ]

    def __str__(self):
        return self.reference_no or self.title or str(self.pk)

    @property
    def display_name(self):
        """Tên hiển thị: kỳ định kỳ → 'tên · kỳ i'; OTHER → title; DOCUMENT → số hiệu."""
        if self.periodic_plan_id:
            return f"{self.periodic_plan.name} · Kỳ {self.period_index}"
        return self.title or self.reference_no

    @property
    def is_open(self):
        return self.status == RecordStatus.OPEN

    @property
    def is_archived(self):
        return self.archived_at is not None

    def clean(self):
        super().clean()
        # v1 (ADR-002): a record's folder must share its unit AND owner department.
        if self.folder_id and (
            self.folder.unit_id != self.unit_id or self.folder.owner_department_id != self.owner_department_id
        ):
            raise ValidationError({"folder": "Nhóm hồ sơ phải cùng đơn vị và cùng phòng chủ trì với hồ sơ."})
        if self.task_kind == TaskKind.OTHER and not self.title:
            raise ValidationError({"title": "Nhiệm vụ khác bắt buộc có tên nhiệm vụ."})
        if self.task_kind == TaskKind.DOCUMENT and not self.reference_no:
            raise ValidationError({"reference_no": "Văn bản bắt buộc có số hiệu."})
        if self.periodic_plan_id:
            if self.periodic_plan.unit_id != self.unit_id or (
                self.periodic_plan.owner_department_id != self.owner_department_id
            ):
                raise ValidationError(
                    {"periodic_plan": "Kỳ định kỳ phải cùng đơn vị và phòng chủ trì với kế hoạch."}
                )


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

    @property
    def correction(self):
        """The single correction event for this result, or None (prefetch 'corrections')."""
        return self.corrections.first()

    @property
    def effective_status(self):
        c = self.correction
        if c is None:
            return "Có hiệu lực"
        return "Đã được thay thế" if c.kind == CorrectionKind.CORRECT else "Đã hủy hiệu lực"


class CorrectionKind(models.TextChoices):
    CORRECT = "CORRECT", "Đính chính"
    REVOKE = "REVOKE", "Hủy hiệu lực"


class ResultCorrection(models.Model):
    """Append-only business correction of an immutable ResultReference.

    The original result row is never updated or deleted — the same PostgreSQL
    immutability trigger covers this table too. `replacement` (CORRECT only) is the
    new ResultReference that takes effect; the old one stays in history.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result = models.ForeignKey(ResultReference, on_delete=models.PROTECT, related_name="corrections")
    kind = models.CharField(max_length=10, choices=CorrectionKind.choices)
    replacement = models.ForeignKey(
        ResultReference, on_delete=models.PROTECT, null=True, blank=True, related_name="supersedes"
    )
    reason = models.CharField("Lý do", max_length=300)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["result"], name="uniq_correction_per_result"),
            models.CheckConstraint(
                condition=(
                    Q(kind="CORRECT", replacement__isnull=False) | Q(kind="REVOKE", replacement__isnull=True)
                ),
                name="correction_replacement_consistent",
            ),
        ]


class ShareAccess(models.TextChoices):
    # v1 has VIEWER only (DECISIONS §2): a direct share never grants submit/edit/assign rights.
    VIEWER = "VIEWER", "Chỉ xem"


class RecordShare(models.Model):
    """Explicit single-record read grant. Soft-revoked via revoked_at; never hard-deleted."""

    record = models.ForeignKey(WorkRecord, on_delete=models.PROTECT, related_name="shares")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="record_shares")
    access = models.CharField(max_length=20, choices=ShareAccess.choices, default=ShareAccess.VIEWER)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "user"],
                condition=Q(revoked_at__isnull=True),
                name="uniq_active_record_share",
            )
        ]
        indexes = [models.Index(fields=["user", "revoked_at"])]

    @property
    def is_active(self):
        return self.revoked_at is None

    def clean(self):
        super().clean()
        if self.record_id and self.user_id and self.user.unit_id != self.record.unit_id:
            raise ValidationError({"user": "Người được chia sẻ phải thuộc cùng đơn vị."})

    def revoke(self):
        if self.revoked_at is not None:
            return
        type(self).objects.filter(pk=self.pk, revoked_at__isnull=True).update(revoked_at=Now())
        self.refresh_from_db()
