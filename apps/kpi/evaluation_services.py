"""Evaluation + finalize + correction (PLAN WP5).

- Evaluation pinned to the ACTIVE policy version at creation (MVP: version locked
  per record; §5.1 notes plan-period locking as a decided alternative).
- Finalize requires: KPI_SCORE_FINALIZE grant on the record's department scope,
  policy still ACTIVE (§0: scoring only under ACTIVE config), marks complete,
  record DONE (OPEN stays draft/preview — WP5 gate).
- Optimistic concurrency via row_version; finalize is idempotent (double POST
  returns the existing snapshot).
- Corrections are append-only: new snapshot revision + KpiScoreCorrection row;
  the old snapshot stays untouched.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import audit_append
from apps.records.models import RecordAssignee, RecordStatus, WorkRecord
from apps.records.timeutils import db_now, local_date

from . import policies
from .models import (
    EvaluationStatus,
    KpiCriterionMark,
    KpiEvaluation,
    KpiPolicyVersion,
    KpiScoreCorrection,
    KpiScoreSnapshot,
    PolicyVersionStatus,
)
from .reminder_services import valid_reminder_count
from .scoring import compute_score


def _evaluation_in_unit(user, evaluation_id):
    try:
        return KpiEvaluation.objects.select_related("record", "policy_version").get(
            pk=evaluation_id, unit_id=user.unit_id
        )
    except KpiEvaluation.DoesNotExist:
        raise KpiEvaluation.DoesNotExist("Không tìm thấy đánh giá.") from None


def active_policy_version(unit_id, task_kind):
    return KpiPolicyVersion.objects.filter(
        family__unit_id=unit_id, family__task_kind=task_kind,
        status=PolicyVersionStatus.ACTIVE,
    ).first()


def late_days_of(record, cutoff=None):
    """VN-local late days vs due_at; 0 when on/before deadline or not completed."""
    if not record.completed_at:
        return 0
    delta = local_date(record.completed_at) - local_date(record.due_at)
    return max(0, delta.days)


def _assert_assignee(record, subject_user_id):
    if not RecordAssignee.objects.filter(
        record=record, user_id=subject_user_id, is_active=True
    ).exists():
        raise ValidationError("Đối tượng chấm phải là người được giao nhiệm vụ.")


@transaction.atomic
def get_or_create_evaluation(actor, *, record_id, subject_user_id):
    try:
        record = WorkRecord.objects.get(pk=record_id, unit_id=actor.unit_id)
    except WorkRecord.DoesNotExist:
        raise WorkRecord.DoesNotExist("Không tìm thấy nhiệm vụ.") from None
    policies.require(policies.can_evaluate(actor, record.owner_department_id))
    _assert_assignee(record, subject_user_id)
    existing = KpiEvaluation.objects.filter(record=record, subject_user_id=subject_user_id).first()
    if existing:
        return existing, False
    version = active_policy_version(record.unit_id, record.task_kind)
    if version is None:
        raise ValidationError(
            "Chưa có cấu hình KPI ACTIVE cho loại nhiệm vụ này — chỉ chấm khi cấu hình đã kích hoạt."
        )
    evaluation = KpiEvaluation.objects.create(
        unit_id=actor.unit_id, record=record, subject_user_id=subject_user_id,
        policy_version=version, assessor=actor,
    )
    return evaluation, True


@transaction.atomic
def save_marks(actor, evaluation_id, marks, expected_row_version=None):
    """marks: {criterion_id: achievement_percent}. Partial saves allowed; finalize requires full."""
    evaluation = _locked_evaluation(actor, evaluation_id)
    policies.require(policies.can_evaluate(actor, evaluation.record.owner_department_id))
    _require_draft_and_version(evaluation, expected_row_version)
    valid_ids = {str(c.pk) for c in evaluation.policy_version.criteria.all()}
    for criterion_id, value in marks.items():
        if criterion_id not in valid_ids:
            raise ValidationError("Tiêu chí không thuộc phiên bản cấu hình của đánh giá.")
        value = Decimal(str(value))
        if not (Decimal("0") <= value <= Decimal("100")):
            raise ValidationError("% đạt phải trong khoảng 0–100.")
        mark, _created = KpiCriterionMark.objects.get_or_create(
            evaluation=evaluation, criterion_id=criterion_id,
            defaults={"achievement_percent": value},
        )
        if not _created:
            mark.achievement_percent = value
            mark.save(update_fields=["achievement_percent"])
    evaluation.row_version += 1
    evaluation.assessor = actor
    evaluation.save(update_fields=["row_version", "assessor"])
    audit_append(AuditAction.KPI_EVALUATION_UPDATED, unit=actor.unit_id, actor=actor,
                 record=evaluation.record, evaluation=str(evaluation.pk))
    return evaluation


def _locked_evaluation(actor, evaluation_id):
    evaluation = _evaluation_in_unit(actor, evaluation_id)
    return KpiEvaluation.objects.select_for_update().get(pk=evaluation.pk)


def _require_draft_and_version(evaluation, expected_row_version):
    if evaluation.status != EvaluationStatus.DRAFT:
        raise ValidationError("Đánh giá đã chốt — không sửa được.")
    if expected_row_version is not None and evaluation.row_version != int(expected_row_version):
        raise ValidationError("Dữ liệu đã thay đổi — tải lại trang trước khi lưu.")


def score_preview(evaluation, cutoff=None):
    """Server-side preview; also used by finalize so client-sent scores never matter."""
    marks = {str(m.criterion_id): m.achievement_percent for m in evaluation.marks.all()}
    record = evaluation.record
    reminders = valid_reminder_count(record, evaluation.subject_user_id, cutoff)
    return compute_score(
        evaluation.policy_version, marks,
        late_days_of(record, cutoff), reminders,
    )


def effective_snapshot(evaluation):
    """The one current revision = snapshot never superseded by a correction."""
    superseded = KpiScoreCorrection.objects.filter(evaluation=evaluation).values_list(
        "supersedes_snapshot_id", flat=True
    )
    return (
        evaluation.snapshots.exclude(pk__in=superseded).order_by("-revision").first()
    )


@transaction.atomic
def finalize_evaluation(actor, evaluation_id, expected_row_version=None):
    evaluation = _locked_evaluation(actor, evaluation_id)
    if evaluation.status == EvaluationStatus.FINALIZED:
        return effective_snapshot(evaluation)  # idempotent double-POST
    policies.require(policies.can_finalize(actor, evaluation.record.owner_department_id))
    _require_draft_and_version(evaluation, expected_row_version)
    if evaluation.policy_version.status != PolicyVersionStatus.ACTIVE:
        raise ValidationError(
            "Cấu hình KPI của đánh giá không còn ACTIVE — tạo đánh giá mới với phiên bản hiệu lực."
        )
    record = evaluation.record
    if record.status != RecordStatus.DONE:
        raise ValidationError("Chỉ chốt điểm khi nhiệm vụ đã hoàn thành (WP5 gate).")
    criteria = list(evaluation.policy_version.criteria.all())
    marked = {str(m.criterion_id) for m in evaluation.marks.all()}
    missing = [c.code for c in criteria if str(c.pk) not in marked]
    if missing:
        raise ValidationError(f"Chưa chấm đủ tiêu chí: {', '.join(missing)}.")
    now = db_now()
    result = score_preview(evaluation, cutoff=now)
    snapshot = KpiScoreSnapshot.objects.create(
        evaluation=evaluation, revision=1,
        base_score=result["base_score"], late_days=result["late_days"],
        reminder_count=result["reminder_count"],
        late_deduction_percent=result["late_deduction_percent"],
        reminder_deduction_percent=result["reminder_deduction_percent"],
        strategy=result["strategy"], final_score=result["final_score"],
        policy_fingerprint=evaluation.policy_version.fingerprint,
        source_cutoff_at=now,
    )
    evaluation.status = EvaluationStatus.FINALIZED
    evaluation.finalized_by = actor
    evaluation.finalized_at = now
    evaluation.row_version += 1
    evaluation.save(update_fields=["status", "finalized_by", "finalized_at", "row_version"])
    audit_append(AuditAction.KPI_EVALUATION_FINALIZED, unit=actor.unit_id, actor=actor,
                 record=record, evaluation=str(evaluation.pk),
                 final_score=str(snapshot.final_score))
    return snapshot


@transaction.atomic
def correct_score(actor, evaluation_id, *, reason, marks=None, expected_row_version=None):
    """Append-only correction: supersedes the effective snapshot with a new revision."""
    if not reason.strip():
        raise ValidationError("Cần nhập lý do điều chỉnh điểm.")
    evaluation = _locked_evaluation(actor, evaluation_id)
    policies.require(policies.can_correct_score(actor, evaluation.record.owner_department_id))
    if evaluation.status != EvaluationStatus.FINALIZED:
        raise ValidationError("Chỉ điều chỉnh điểm đã chốt.")
    if expected_row_version is not None and evaluation.row_version != int(expected_row_version):
        raise ValidationError("Dữ liệu đã thay đổi — tải lại trang trước khi điều chỉnh.")
    current = effective_snapshot(evaluation)
    if current is None:
        raise ValidationError("Đánh giá chưa có snapshot hiệu lực.")
    if marks is not None:
        valid_ids = {str(c.pk) for c in evaluation.policy_version.criteria.all()}
        for criterion_id, value in marks.items():
            if criterion_id not in valid_ids:
                raise ValidationError("Tiêu chí không thuộc phiên bản cấu hình của đánh giá.")
            value = Decimal(str(value))
            if not (Decimal("0") <= value <= Decimal("100")):
                raise ValidationError("% đạt phải trong khoảng 0–100.")
            KpiCriterionMark.objects.update_or_create(
                evaluation=evaluation, criterion_id=criterion_id,
                defaults={"achievement_percent": value},
            )
    now = db_now()
    result = score_preview(evaluation, cutoff=now)
    new_snapshot = KpiScoreSnapshot.objects.create(
        evaluation=evaluation, revision=current.revision + 1,
        base_score=result["base_score"], late_days=result["late_days"],
        reminder_count=result["reminder_count"],
        late_deduction_percent=result["late_deduction_percent"],
        reminder_deduction_percent=result["reminder_deduction_percent"],
        strategy=result["strategy"], final_score=result["final_score"],
        policy_fingerprint=evaluation.policy_version.fingerprint,
        source_cutoff_at=now,
    )
    KpiScoreCorrection.objects.create(
        evaluation=evaluation, supersedes_snapshot=current,
        replacement_snapshot=new_snapshot, reason=reason.strip()[:200],
        requested_by=actor, approved_by=actor,
    )
    evaluation.row_version += 1
    evaluation.save(update_fields=["row_version"])
    audit_append(AuditAction.KPI_SCORE_CORRECTED, unit=actor.unit_id, actor=actor,
                 record=evaluation.record, evaluation=str(evaluation.pk),
                 before=str(current.pk), after=str(new_snapshot.pk))
    return new_snapshot
