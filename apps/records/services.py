"""Domain services: own transactions, locking, audit and notification side effects."""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from apps.audit.models import AuditAction
from apps.audit.services import audit_append

from . import policies
from .codes import InvalidCode, clean_display_code, normalize_code
from .models import (
    CorrectionKind,
    PeriodicPlan,
    RecordAssignee,
    RecordStatus,
    RecordWatcher,
    ResultCorrection,
    ResultReference,
    TaskKind,
    WorkRecord,
)
from .timeutils import due_at_for_date


def _ids(users):
    return sorted(str(u.pk) for u in users)


def _validate_users(allowed_qs, users, label):
    users = list(dict.fromkeys(users))
    allowed = set(allowed_qs.filter(pk__in=[u.pk for u in users]).values_list("pk", flat=True))
    bad = [u for u in users if u.pk not in allowed]
    if bad:
        raise ValidationError(f"{label} ngoài phạm vi được phép: " + ", ".join(str(u) for u in bad))
    return users


def _lock(record_id, actor):
    """Lock the record row; re-check visibility under the lock so out-of-scope ids look nonexistent."""
    record = WorkRecord.objects.select_for_update().filter(pk=record_id).first()
    if record is None or not policies.can_view_record(actor, record):
        raise WorkRecord.DoesNotExist
    return record


def _normalize_reference(task_kind, reference_no):
    """DOCUMENT requires a valid code; OTHER may carry one optionally or none at all."""
    if not (reference_no or "").strip():
        if task_kind == TaskKind.DOCUMENT:
            raise ValidationError("Văn bản bắt buộc có số hiệu.")
        return "", ""
    try:
        display = clean_display_code(reference_no)
    except InvalidCode as e:
        raise ValidationError(str(e)) from e
    return display, normalize_code(display)


@transaction.atomic
def create_record(
    actor,
    *,
    owner_department,
    due_date,
    assignees,
    reference_no=None,
    task_kind=TaskKind.DOCUMENT,
    title="",
    task_code="",
    watchers=(),
    description_short="",
    periodic_plan=None,
    period_index=None,
):
    policies.require(policies.can_create_record(actor, owner_department))
    if task_kind not in TaskKind.values:
        raise ValidationError("Loại nhiệm vụ không hợp lệ.")
    display, normalized = _normalize_reference(task_kind, reference_no)
    title = (title or "").strip()[:200]
    task_code = (task_code or "").strip()[:64]
    if task_kind == TaskKind.OTHER and not title:
        raise ValidationError("Nhiệm vụ khác bắt buộc có tên nhiệm vụ.")
    assignees = _validate_users(policies.assignable_users(actor, owner_department), assignees, "Người xử lý")
    if not assignees:
        raise ValidationError("Cần chọn ít nhất một người xử lý.")
    watchers = _validate_users(policies.watchable_users(actor), watchers, "Người theo dõi")
    record = WorkRecord.objects.create(
        unit_id=actor.unit_id,
        task_kind=task_kind,
        title=title,
        task_code=task_code,
        reference_no=display,
        reference_no_normalized=normalized,
        periodic_plan=periodic_plan,
        period_index=period_index,
        owner_department=owner_department,
        assigner=actor,
        created_by=actor,
        due_at=due_at_for_date(due_date),
        description_short=(description_short or "").strip()[:200],
    )
    RecordAssignee.objects.bulk_create(
        RecordAssignee(record=record, user=u, added_by=actor) for u in assignees
    )
    RecordWatcher.objects.bulk_create(RecordWatcher(record=record, user=u, added_by=actor) for u in watchers)
    audit_append(
        AuditAction.RECORD_CREATED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        reference_no=display,
        owner_department=str(owner_department.pk),
        due_at=record.due_at.isoformat(),
        assignees=_ids(assignees),
        watchers=_ids(watchers),
    )
    record.refresh_from_db()
    return record


@transaction.atomic
def create_periodic_plan(
    actor,
    *,
    name,
    owner_department,
    year,
    due_dates,
    assignees,
    task_kind=TaskKind.DOCUMENT,
    reference_no=None,
    task_code="",
    description_short="",
):
    """Tạo 1 PeriodicPlan + 1..12 WorkRecord con trong cùng một transaction.

    unique(periodic_plan, period_index) chặn trùng index ở DB; validate count 1..12,
    mọi ngày thuộc `year`, không trùng ngày. Mỗi kỳ có deadline/status/results riêng.
    """
    policies.require(policies.can_create_record(actor, owner_department))
    name = (name or "").strip()[:200]
    if not name:
        raise ValidationError("Kế hoạch định kỳ bắt buộc có tên.")
    if task_kind not in TaskKind.values:
        raise ValidationError("Loại nhiệm vụ không hợp lệ.")
    display, normalized = _normalize_reference(task_kind, reference_no)
    dates = sorted(set(due_dates))
    if len(dates) != len(due_dates):
        raise ValidationError("Các ngày hạn của các kỳ không được trùng nhau.")
    if not 1 <= len(dates) <= 12:
        raise ValidationError("Văn bản định kỳ phải có từ 1 đến 12 kỳ trong năm.")
    bad = [d for d in dates if d.year != year]
    if bad:
        raise ValidationError(f"Mọi kỳ phải có hạn thuộc năm {year}.")
    assignees = _validate_users(policies.assignable_users(actor, owner_department), assignees, "Người xử lý")
    if not assignees:
        raise ValidationError("Cần chọn ít nhất một người xử lý.")
    task_code = (task_code or "").strip()[:64]
    # EU-03: mỗi kỳ một mã duy nhất (ràng buộc unique(unit, task_code) với mã
    # không rỗng). Kiểm tra va chạm trước để form trả lỗi 400 thay vì 500.
    child_codes = [f"{task_code}.K{idx:02d}" if task_code else "" for idx in range(1, len(dates) + 1)]
    if task_code and WorkRecord.objects.filter(unit_id=actor.unit_id, task_code__in=child_codes).exists():
        raise ValidationError(f"Mã nhiệm vụ '{task_code}' đã được dùng cho kỳ định kỳ khác; chọn mã khác.")
    plan = PeriodicPlan.objects.create(
        unit_id=actor.unit_id,
        name=name,
        task_kind=task_kind,
        reference_no=display,
        year=year,
        owner_department=owner_department,
        created_by=actor,
    )
    records = []
    for idx, day in enumerate(dates, start=1):
        rec = WorkRecord.objects.create(
            unit_id=actor.unit_id,
            task_kind=task_kind,
            title=name,
            task_code=child_codes[idx - 1],
            reference_no=display,
            reference_no_normalized=normalized,
            periodic_plan=plan,
            period_index=idx,
            owner_department=owner_department,
            assigner=actor,
            created_by=actor,
            due_at=due_at_for_date(day),
            description_short=(description_short or "").strip()[:200],
        )
        RecordAssignee.objects.bulk_create(
            RecordAssignee(record=rec, user=u, added_by=actor) for u in assignees
        )
        audit_append(
            AuditAction.RECORD_CREATED,
            unit=rec.unit_id,
            actor=actor,
            record=rec,
            reference_no=display,
            owner_department=str(owner_department.pk),
            due_at=rec.due_at.isoformat(),
            assignees=_ids(assignees),
            periodic_plan=str(plan.pk),
            period_index=idx,
        )
        records.append(rec)
    audit_append(
        AuditAction.PERIODIC_PLAN_CREATED,
        unit=plan.unit_id,
        actor=actor,
        record=records[0],
        periodic_plan=str(plan.pk),
        name=name,
        year=year,
        period_count=len(records),
        task_kind=task_kind,
    )
    return plan


@transaction.atomic
def complete_other_task(actor, record_id):
    """D12 conservative default: nhiệm vụ OTHER hoàn thành bằng xác nhận của assignee,
    không qua số hiệu kết quả. Một transaction + lock + audit giống submit.
    """
    record = _lock(record_id, actor)
    if record.task_kind != TaskKind.OTHER:
        raise ValidationError("Chỉ nhiệm vụ khác mới hoàn thành bằng xác nhận.")
    policies.require(policies.can_submit_result(actor, record))
    if record.status == RecordStatus.DONE:
        raise ValidationError("Nhiệm vụ đã hoàn thành trước đó.")
    WorkRecord.objects.filter(pk=record.pk, status=RecordStatus.OPEN).update(
        status=RecordStatus.DONE, completed_at=Now(), completed_by=actor, updated_at=Now()
    )
    record.refresh_from_db()
    audit_append(
        AuditAction.OTHER_TASK_COMPLETED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        title=record.title,
    )
    from apps.notifications.services import resolve_record_notifications

    resolve_record_notifications(record, actor=actor, reason="other_completed")
    return record


def _touch(record):
    WorkRecord.objects.filter(pk=record.pk).update(updated_at=Now())


def _sync_relation(model, record, actor, wanted):
    current = {r.user_id: r for r in model.objects.filter(record=record)}
    before = sorted(str(uid) for uid, r in current.items() if r.is_active)
    wanted_ids = {u.pk for u in wanted}
    for uid, row in current.items():
        if row.is_active and uid not in wanted_ids:
            model.objects.filter(pk=row.pk).update(is_active=False)
        elif not row.is_active and uid in wanted_ids:
            model.objects.filter(pk=row.pk).update(is_active=True)
    for u in wanted:
        if u.pk not in current:
            model.objects.create(record=record, user=u, added_by=actor)
    after = sorted(str(u.pk) for u in wanted)
    removed = set(before) - set(after)
    return before, after, removed


@transaction.atomic
def update_assignment(actor, record_id, assignees):
    from apps.notifications.services import resolve_record_notifications

    record = _lock(record_id, actor)
    policies.require(policies.can_manage_assignment(actor, record))
    assignees = _validate_users(
        policies.assignable_users(actor, record.owner_department), assignees, "Người xử lý"
    )
    if not assignees:
        raise ValidationError("Cần chọn ít nhất một người xử lý.")
    before, after, removed = _sync_relation(RecordAssignee, record, actor, assignees)
    if before == after:
        return record
    _touch(record)
    audit_append(
        AuditAction.ASSIGNMENT_CHANGED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        reference_no=record.reference_no,
        before=before,
        after=after,
    )
    if removed:
        resolve_record_notifications(record, actor=actor, recipient_ids=removed, reason="assignee_removed")
    return record


@transaction.atomic
def update_watchers(actor, record_id, watchers):
    record = _lock(record_id, actor)
    policies.require(policies.can_manage_watchers(actor, record))
    watchers = _validate_users(policies.watchable_users(actor), watchers, "Người theo dõi")
    before, after, _ = _sync_relation(RecordWatcher, record, actor, watchers)
    if before == after:
        return record
    _touch(record)
    audit_append(
        AuditAction.WATCHERS_CHANGED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        reference_no=record.reference_no,
        before=before,
        after=after,
    )
    return record


@transaction.atomic
def update_deadline(actor, record_id, due_date):
    from apps.notifications.services import resolve_record_notifications

    record = _lock(record_id, actor)
    policies.require(policies.can_edit_deadline(actor, record))
    new_due = due_at_for_date(due_date)
    if new_due == record.due_at:
        return record
    before = record.due_at.isoformat()
    WorkRecord.objects.filter(pk=record.pk).update(due_at=new_due, updated_at=Now())
    record.refresh_from_db()
    audit_append(
        AuditAction.DEADLINE_CHANGED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        reference_no=record.reference_no,
        before=before,
        after=record.due_at.isoformat(),
    )
    resolve_record_notifications(record, actor=actor, reason="deadline_changed")
    return record


@dataclass(frozen=True)
class SubmitOutcome:
    result: ResultReference
    created: bool
    completed_record: bool


def submit_result_reference(actor, record_id, code):
    """ARCHITECTURE §5. One transaction, record row locked; first valid result closes the record.

    Retry/duplicate of the same normalized code returns the existing result without new events.
    """
    try:
        display = clean_display_code(code)
    except InvalidCode as e:
        raise ValidationError(str(e)) from e
    normalized = normalize_code(display)
    with transaction.atomic():
        record = WorkRecord.objects.select_for_update().filter(pk=record_id).first()
        if record is None or not policies.can_view_record(actor, record):
            raise WorkRecord.DoesNotExist
        if not policies.can_submit_result(actor, record):
            raise PermissionDenied("Chỉ người được giao đang hoạt động mới được nộp số hiệu kết quả.")
        if record.task_kind == TaskKind.OTHER:
            raise ValidationError(
                "Nhiệm vụ khác hoàn thành xác nhận của người thực hiện, không qua số hiệu (D12)."
            )
        existing = ResultReference.objects.filter(record=record, normalized_code=normalized).first()
        if existing:
            return SubmitOutcome(existing, created=False, completed_record=False)
        try:
            with transaction.atomic():
                result = ResultReference.objects.create(
                    record=record, code=display, normalized_code=normalized, submitted_by=actor
                )
        except IntegrityError:
            existing = ResultReference.objects.get(record=record, normalized_code=normalized)
            return SubmitOutcome(existing, created=False, completed_record=False)
        audit_append(
            AuditAction.RESULT_SUBMITTED,
            unit=record.unit_id,
            actor=actor,
            record=record,
            reference_no=record.reference_no,
            result_id=str(result.pk),
            code=display,
        )
        completed = False
        if record.status == RecordStatus.OPEN:
            updated = WorkRecord.objects.filter(pk=record.pk, status=RecordStatus.OPEN).update(
                status=RecordStatus.DONE, completed_at=Now(), completed_by=actor, updated_at=Now()
            )
            if updated == 1:
                completed = True
                record.refresh_from_db()
                audit_append(
                    AuditAction.RECORD_COMPLETED,
                    unit=record.unit_id,
                    actor=actor,
                    record=record,
                    reference_no=record.reference_no,
                    result_id=str(result.pk),
                    code=display,
                )
                from apps.notifications.services import resolve_record_notifications

                resolve_record_notifications(record, actor=actor, reason="record_done")
        return SubmitOutcome(result, created=True, completed_record=completed)


def _record_audit(actor, record, action, **meta):
    audit_append(
        action, unit=record.unit_id, actor=actor, record=record, reference_no=record.reference_no, **meta
    )


@transaction.atomic
def update_reference_no(actor, record_id, reference_no):
    record = _lock(record_id, actor)
    policies.require(policies.can_edit_record_metadata(actor, record))
    try:
        display = clean_display_code(reference_no)
    except InvalidCode as e:
        raise ValidationError(str(e)) from e
    if display == record.reference_no:
        return record
    before = record.reference_no
    WorkRecord.objects.filter(pk=record.pk).update(
        reference_no=display,
        reference_no_normalized=normalize_code(display),
        updated_at=Now(),
    )
    record.refresh_from_db()
    _record_audit(
        actor,
        record,
        AuditAction.RECORD_UPDATED,
        field="reference_no",
        before=before,
        after=display,
    )
    return record


@transaction.atomic
def update_description(actor, record_id, text):
    record = _lock(record_id, actor)
    policies.require(policies.can_edit_record_metadata(actor, record))
    text = (text or "").strip()[:200]
    if text == record.description_short:
        return record
    before = record.description_short
    WorkRecord.objects.filter(pk=record.pk).update(description_short=text, updated_at=Now())
    record.refresh_from_db()
    _record_audit(
        actor, record, AuditAction.RECORD_UPDATED, field="description_short", before=before, after=text
    )
    return record


@transaction.atomic
def update_owner_department(actor, record_id, department):
    """Owner-dept reassignment stays inside the actor's creatable scope — no cross-unit move and
    no self-escalation to another department the actor could not create in."""
    record = _lock(record_id, actor)
    policies.require(policies.can_edit_record_metadata(actor, record))
    if department.pk == record.owner_department_id:
        return record
    if department.unit_id != record.unit_id or not department.is_active:
        raise ValidationError("Phòng chủ trì không hợp lệ.")
    policies.require(
        policies.creatable_departments(actor).filter(pk=department.pk).exists(),
        "Bạn không có quyền chuyển hồ sơ sang phòng này.",
    )
    if record.folder_id and record.folder.owner_department_id != department.pk:
        raise ValidationError("Hồ sơ đang thuộc nhóm hồ sơ của phòng khác; hãy chuyển nhóm hồ sơ trước.")
    before = record.owner_department.name
    WorkRecord.objects.filter(pk=record.pk).update(owner_department=department, updated_at=Now())
    record.refresh_from_db()
    _record_audit(
        actor,
        record,
        AuditAction.RECORD_UPDATED,
        field="owner_department",
        before=before,
        after=department.name,
    )
    return record


@transaction.atomic
def archive_record(actor, record_id, reason):
    """Archive replaces hard delete (CONTEXT): OPEN + no results + managed scope only."""
    from apps.notifications.services import resolve_record_notifications

    record = _lock(record_id, actor)
    policies.require(policies.can_archive_record(actor, record))
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Cần nhập lý do lưu trữ.")
    WorkRecord.objects.filter(pk=record.pk).update(
        archived_at=Now(),
        archived_by=actor,
        archive_reason=reason[:300],
        updated_at=Now(),
    )
    record.refresh_from_db()
    _record_audit(actor, record, AuditAction.RECORD_ARCHIVED, reason=reason[:300])
    resolve_record_notifications(record, actor=actor, reason="record_archived")
    return record


@transaction.atomic
def restore_record(actor, record_id):
    record = _lock(record_id, actor)
    policies.require(policies.can_restore_record(actor, record))
    before_reason = record.archive_reason
    WorkRecord.objects.filter(pk=record.pk).update(
        archived_at=None, archived_by=None, archive_reason="", updated_at=Now()
    )
    record.refresh_from_db()
    _record_audit(actor, record, AuditAction.RECORD_RESTORED, archived_reason=before_reason)
    return record


def _locked_result(record, result_id):
    result = record.results.select_for_update().filter(pk=result_id).first()
    if result is None:
        raise ResultReference.DoesNotExist
    return result


def _require_uncorrected(result):
    if result.corrections.exists():
        raise ValidationError("Số hiệu này đã được đính chính hoặc hủy hiệu lực trước đó.")


@transaction.atomic
def correct_result_reference(actor, record_id, result_id, new_code, reason):
    """Append-only correction (CONTEXT H03 kept): original row stays, a replacement
    ResultReference is created and linked through a ResultCorrection event."""
    record = _lock(record_id, actor)
    result = _locked_result(record, result_id)
    policies.require(policies.can_correct_result(actor, record, result))
    _require_uncorrected(result)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Cần nhập lý do đính chính.")
    try:
        display = clean_display_code(new_code)
    except InvalidCode as e:
        raise ValidationError(str(e)) from e
    normalized = normalize_code(display)
    if ResultReference.objects.filter(record=record, normalized_code=normalized).exists():
        raise ValidationError("Số hiệu thay thế đã tồn tại trên hồ sơ này.")
    replacement = ResultReference.objects.create(
        record=record, code=display, normalized_code=normalized, submitted_by=actor
    )
    try:
        with transaction.atomic():
            ResultCorrection.objects.create(
                result=result,
                kind=CorrectionKind.CORRECT,
                replacement=replacement,
                reason=reason[:300],
                actor=actor,
            )
    except IntegrityError:
        raise ValidationError(
            "Số hiệu này vừa được đính chính hoặc hủy hiệu lực bởi thao tác khác."
        ) from None
    _record_audit(
        actor,
        record,
        AuditAction.RESULT_CORRECTED,
        result_id=str(result.pk),
        before=result.code,
        after=display,
        replacement_id=str(replacement.pk),
        reason=reason[:300],
    )
    return replacement


@transaction.atomic
def revoke_result_reference(actor, record_id, result_id, reason):
    """Marks a result revoked via an append-only event. A DONE record must keep at least one
    effective result — revoking the last one is refused (use a correction instead)."""
    record = _lock(record_id, actor)
    result = _locked_result(record, result_id)
    policies.require(policies.can_correct_result(actor, record, result))
    _require_uncorrected(result)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Cần nhập lý do hủy hiệu lực.")
    if record.status == RecordStatus.DONE and record.results.filter(corrections__isnull=True).count() <= 1:
        raise ValidationError(
            "Hồ sơ đã hoàn thành phải giữ ít nhất một số hiệu còn hiệu lực; hãy đính chính thay thế."
        )
    try:
        with transaction.atomic():
            ResultCorrection.objects.create(
                result=result, kind=CorrectionKind.REVOKE, reason=reason[:300], actor=actor
            )
    except IntegrityError:
        raise ValidationError(
            "Số hiệu này vừa được đính chính hoặc hủy hiệu lực bởi thao tác khác."
        ) from None
    _record_audit(
        actor,
        record,
        AuditAction.RESULT_REVOKED,
        result_id=str(result.pk),
        code=result.code,
        reason=reason[:300],
    )
    return record
