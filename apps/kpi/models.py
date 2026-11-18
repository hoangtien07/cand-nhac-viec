"""KPI subsystem schema (PLAN §6.2).

Invariants kept: immutable published policy versions; per user+unit capability grants;
reminder events independent of Notification; per-subject-user evaluation; finalized
score snapshots never overwritten; append-only correction history.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now

from apps.records.models import TaskKind, WorkRecord

from .capabilities import BUSINESS_CAPABILITIES, CAPABILITY_CHOICES, KpiCapability

USER = settings.AUTH_USER_MODEL
DEC_5_2 = {"max_digits": 5, "decimal_places": 2}
DEC_6_2 = {"max_digits": 6, "decimal_places": 2}


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Bảng này chỉ cho phép append (append-only).")

    def delete(self):
        raise PermissionError("Bảng này chỉ cho phép append (append-only).")


class AppendOnlyModel(models.Model):
    """App-layer append-only; PostgreSQL triggers also reject UPDATE/DELETE (kpi 0002)."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Bảng này chỉ cho phép append (append-only).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Bảng này chỉ cho phép append (append-only).")


class KpiPolicyFamily(models.Model):
    """One canonical family per (unit, task_kind) in MVP; row-locked on publish."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="kpi_families")
    task_kind = models.CharField("Loại nhiệm vụ", max_length=10, choices=TaskKind.choices)
    name = models.CharField("Tên bộ thang điểm", max_length=200)
    active_version = models.ForeignKey(
        "KpiPolicyVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["unit", "task_kind"], name="uniq_kpi_family_per_unit_kind")
        ]
        ordering = ["unit", "task_kind"]

    def __str__(self):
        return f"{self.name} ({self.get_task_kind_display()})"


class PolicyVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Bản nháp"
    ACTIVE = "ACTIVE", "Đang áp dụng"
    SUPERSEDED = "SUPERSEDED", "Đã thay thế"


class CombinationStrategy(models.TextChoices):
    MAX_DEDUCTION = "MAX_DEDUCTION", "Trừ mức lớn nhất"
    CAPPED_ADDITIVE = "CAPPED_ADDITIVE", "Cộng dồn có trần"
    MULTIPLICATIVE = "MULTIPLICATIVE", "Nhân hệ số"


class KpiPolicyVersion(models.Model):
    """Immutable after publish. ACTIVE -> SUPERSEDED only, with audit (PLAN §5.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(KpiPolicyFamily, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField("Phiên bản")
    status = models.CharField(
        max_length=12, choices=PolicyVersionStatus.choices, default=PolicyVersionStatus.DRAFT
    )
    max_points = models.DecimalField("Thang điểm tối đa", **DEC_6_2)
    combination_strategy = models.CharField(
        max_length=20, choices=CombinationStrategy.choices, default=CombinationStrategy.MAX_DEDUCTION
    )
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    published_by = models.ForeignKey(USER, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    effective_from = models.DateTimeField(null=True, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["family", "version"], name="uniq_kpi_version_per_family"),
            models.CheckConstraint(condition=models.Q(max_points__gt=0), name="kpi_version_max_points_pos"),
        ]
        ordering = ["family", "-version"]

    def __str__(self):
        return f"{self.family.name} v{self.version} ({self.get_status_display()})"


class KpiCriterion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(KpiPolicyVersion, on_delete=models.PROTECT, related_name="criteria")
    code = models.CharField("Mã tiêu chí", max_length=40)
    title = models.CharField("Tên tiêu chí", max_length=200)
    description_short = models.CharField("Mô tả ngắn", max_length=200, blank=True)
    weight_percent = models.DecimalField("Trọng số %", **DEC_5_2)
    position = models.PositiveSmallIntegerField(default=0)
    required = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "code"], name="uniq_kpi_criterion_code"),
            models.CheckConstraint(
                condition=models.Q(weight_percent__gte=0) & models.Q(weight_percent__lte=100),
                name="kpi_criterion_weight_range",
            ),
        ]
        ordering = ["position", "code"]

    def __str__(self):
        return f"{self.code} — {self.title}"


class PenaltyBandKind(models.TextChoices):
    LATE_DAYS = "LATE_DAYS", "Số ngày trễ hạn"
    REMINDER_COUNT = "REMINDER_COUNT", "Số lần nhắc nhở"


class KpiPenaltyBand(models.Model):
    """Bands per (version, kind) must cover [0, +∞) without gaps/overlaps — checked at publish."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(KpiPolicyVersion, on_delete=models.PROTECT, related_name="penalty_bands")
    kind = models.CharField(max_length=15, choices=PenaltyBandKind.choices)
    min_value = models.PositiveSmallIntegerField()
    max_value = models.PositiveSmallIntegerField(null=True, blank=True)  # NULL = open-ended
    deduction_percent = models.DecimalField("% trừ", **DEC_5_2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_value__isnull=True) | models.Q(max_value__gte=models.F("min_value")),
                name="kpi_penalty_band_minmax",
            ),
            models.CheckConstraint(
                condition=models.Q(deduction_percent__gte=0) & models.Q(deduction_percent__lte=100),
                name="kpi_penalty_band_deduction_range",
            ),
        ]
        ordering = ["kind", "min_value"]

    def __str__(self):
        upper = "+" if self.max_value is None else f"-{self.max_value}"
        return f"{self.get_kind_display()} {self.min_value}{upper}: -{self.deduction_percent}%"


class GrantScope(models.TextChoices):
    UNIT = "UNIT", "Toàn đơn vị"
    DEPARTMENT = "DEPARTMENT", "Theo tổ/phòng"


class KpiCapabilityGrant(models.Model):
    """Soft-revoke grant; at most one active row per (unit, user, capability, scope, department)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="kpi_grants")
    user = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="kpi_grants")
    capability = models.CharField(max_length=25, choices=CAPABILITY_CHOICES)
    scope = models.CharField(max_length=12, choices=GrantScope.choices)
    department = models.ForeignKey(
        "organization.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    granted_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(USER, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    reason = models.CharField("Lý do/căn cứ phê duyệt", max_length=200, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "user", "capability", "scope", "department"],
                condition=models.Q(revoked_at__isnull=True) & models.Q(department__isnull=False),
                name="uniq_active_kpi_grant_with_dept",
            ),
            models.UniqueConstraint(
                fields=["unit", "user", "capability", "scope"],
                condition=models.Q(revoked_at__isnull=True) & models.Q(department__isnull=True),
                name="uniq_active_kpi_grant_no_dept",
            ),
        ]
        indexes = [models.Index(fields=["unit", "user", "capability", "revoked_at"])]
        ordering = ["unit", "user", "capability"]

    def __str__(self):
        return f"{self.capability} → {self.user} ({self.get_scope_display()})"


class KpiReminderEvent(AppendOnlyModel):
    """Official KPI reminder (deduction-relevant) — separate from Notification (PLAN §4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="+")
    record = models.ForeignKey(WorkRecord, on_delete=models.PROTECT, related_name="kpi_reminders")
    subject_user = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="kpi_reminders")
    actor = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField("Lý do", max_length=200)
    issued_at = models.DateTimeField(db_default=Now(), editable=False)
    idempotency_key = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["unit", "idempotency_key"], name="uniq_kpi_reminder_idem")
        ]
        indexes = [models.Index(fields=["subject_user", "issued_at"]), models.Index(fields=["record"])]

    @property
    def is_revoked(self):
        return hasattr(self, "revocation")


class KpiReminderRevocation(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reminder_event = models.OneToOneField(
        KpiReminderEvent, on_delete=models.PROTECT, related_name="revocation"
    )
    actor = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField("Lý do hủy", max_length=200)
    created_at = models.DateTimeField(db_default=Now(), editable=False)


class EvaluationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Đang đánh giá"
    FINALIZED = "FINALIZED", "Đã chốt"


class KpiEvaluation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="+")
    record = models.ForeignKey(WorkRecord, on_delete=models.PROTECT, related_name="kpi_evaluations")
    subject_user = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="kpi_evaluations")
    policy_version = models.ForeignKey(KpiPolicyVersion, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=12, choices=EvaluationStatus.choices, default=EvaluationStatus.DRAFT)
    row_version = models.PositiveIntegerField(default=1)
    assessor = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    finalized_by = models.ForeignKey(USER, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["record", "subject_user"], name="uniq_kpi_eval_record_subject")
        ]
        indexes = [models.Index(fields=["unit", "subject_user", "status"])]


class KpiCriterionMark(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluation = models.ForeignKey(KpiEvaluation, on_delete=models.PROTECT, related_name="marks")
    criterion = models.ForeignKey(KpiCriterion, on_delete=models.PROTECT, related_name="+")
    achievement_percent = models.DecimalField("% đạt", **DEC_5_2)
    comment_short = models.CharField("Nhận xét ngắn", max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "criterion"], name="uniq_kpi_mark_per_criterion"),
            models.CheckConstraint(
                condition=models.Q(achievement_percent__gte=0) & models.Q(achievement_percent__lte=100),
                name="kpi_mark_achievement_range",
            ),
        ]


class KpiScoreSnapshot(AppendOnlyModel):
    """Frozen at finalize; corrected via KpiScoreCorrection, never UPDATE (PLAN §5.1, §6.2).

    The single effective revision = the snapshot not referenced by any
    KpiScoreCorrection.supersedes_snapshot (resolved in queries, not a mutable flag).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluation = models.ForeignKey(KpiEvaluation, on_delete=models.PROTECT, related_name="snapshots")
    revision = models.PositiveIntegerField()
    base_score = models.DecimalField(**DEC_6_2)
    late_days = models.IntegerField()
    reminder_count = models.IntegerField()
    late_deduction_percent = models.DecimalField(**DEC_5_2)
    reminder_deduction_percent = models.DecimalField(**DEC_5_2)
    strategy = models.CharField(max_length=20, choices=CombinationStrategy.choices)
    final_score = models.DecimalField(**DEC_6_2)
    policy_fingerprint = models.CharField(max_length=64)
    source_cutoff_at = models.DateTimeField()
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "revision"], name="uniq_kpi_snapshot_revision")
        ]
        ordering = ["-created_at"]


class KpiScoreCorrection(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluation = models.ForeignKey(KpiEvaluation, on_delete=models.PROTECT, related_name="corrections")
    supersedes_snapshot = models.ForeignKey(KpiScoreSnapshot, on_delete=models.PROTECT, related_name="+")
    replacement_snapshot = models.ForeignKey(KpiScoreSnapshot, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField("Lý do điều chỉnh", max_length=200)
    requested_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)


# Business capabilities that SYS_ADMIN must never hold (PLAN §5.2).
_SYS_ADMIN_FORBIDDEN = frozenset(BUSINESS_CAPABILITIES)
assert KpiCapability.GRANT_MANAGE not in _SYS_ADMIN_FORBIDDEN
