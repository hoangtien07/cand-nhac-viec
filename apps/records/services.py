"""Domain services: own transactions, locking, audit and notification side effects."""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from apps.audit.models import AuditAction
from apps.audit.services import audit_append

from . import policies
from .codes import InvalidCode, clean_display_code, normalize_code
from .models import RecordAssignee, RecordStatus, RecordWatcher, ResultReference, WorkRecord
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


@transaction.atomic
def create_record(actor, *, reference_no, owner_department, due_date, assignees, watchers=()):
    policies.require(policies.can_create_record(actor, owner_department))
    try:
        display = clean_display_code(reference_no)
    except InvalidCode as e:
        raise ValidationError(str(e)) from e
    assignees = _validate_users(policies.assignable_users(actor, owner_department), assignees, "Người xử lý")
    if not assignees:
        raise ValidationError("Cần chọn ít nhất một người xử lý.")
    watchers = _validate_users(policies.watchable_users(actor), watchers, "Người theo dõi")
    record = WorkRecord.objects.create(
        unit_id=actor.unit_id,
        reference_no=display,
        reference_no_normalized=normalize_code(display),
        owner_department=owner_department,
        assigner=actor,
        created_by=actor,
        due_at=due_at_for_date(due_date),
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
