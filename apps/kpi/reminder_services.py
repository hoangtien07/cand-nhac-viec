"""Official KPI reminder events — append-only, idempotent, scope-checked per request (PLAN WP5)."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.audit.models import AuditAction
from apps.audit.services import audit_append
from apps.records.models import RecordAssignee, WorkRecord

from . import policies
from .models import KpiReminderEvent, KpiReminderRevocation


def _record_in_unit(user, record_id):
    try:
        return WorkRecord.objects.get(pk=record_id, unit_id=user.unit_id)
    except WorkRecord.DoesNotExist:
        raise WorkRecord.DoesNotExist("Không tìm thấy nhiệm vụ.") from None


def _subject_is_assignee(record, subject_user_id):
    return RecordAssignee.objects.filter(
        record=record, user_id=subject_user_id, is_active=True
    ).exists()


@transaction.atomic
def issue_reminder(actor, *, record_id, subject_user_id, reason, idempotency_key):
    """Idempotent on (unit, idempotency_key) — retry/double-POST returns the same event."""
    if not idempotency_key or len(idempotency_key) > 64:
        raise ValidationError("Thiếu idempotency key hợp lệ.")
    if not reason.strip():
        raise ValidationError("Cần nhập lý do nhắc nhở.")
    record = _record_in_unit(actor, record_id)
    policies.require(policies.can_issue_kpi_reminder(actor, record.owner_department_id))
    if not _subject_is_assignee(record, subject_user_id):
        raise ValidationError("Cán bộ nhận nhắc nhở phải là người được giao nhiệm vụ.")
    try:
        with transaction.atomic():  # savepoint: duplicate key only rolls back this insert
            event = KpiReminderEvent.objects.create(
                unit_id=actor.unit_id, record=record, subject_user_id=subject_user_id,
                actor=actor, reason=reason.strip()[:200], idempotency_key=idempotency_key,
            )
    except IntegrityError:
        return KpiReminderEvent.objects.get(
            unit_id=actor.unit_id, idempotency_key=idempotency_key
        )
    audit_append(
        AuditAction.KPI_REMINDER_ISSUED, unit=actor.unit_id, actor=actor, record=record,
        event=str(event.pk), subject=str(subject_user_id),
    )
    return event


@transaction.atomic
def revoke_reminder(actor, *, event_id, reason):
    """Append-only revocation; unique(reminder_event) makes double-POST safe."""
    if not reason.strip():
        raise ValidationError("Cần nhập lý do hủy nhắc nhở.")
    try:
        event = KpiReminderEvent.objects.select_related("record").get(
            pk=event_id, unit_id=actor.unit_id
        )
    except KpiReminderEvent.DoesNotExist:
        raise KpiReminderEvent.DoesNotExist("Không tìm thấy sự kiện nhắc nhở.") from None
    # grant is re-checked at revoke time (PLAN §5.3)
    policies.require(policies.can_issue_kpi_reminder(actor, event.record.owner_department_id))
    try:
        with transaction.atomic():
            revocation = KpiReminderRevocation.objects.create(
                reminder_event=event, actor=actor, reason=reason.strip()[:200]
            )
    except IntegrityError:
        return KpiReminderRevocation.objects.get(reminder_event=event)
    audit_append(
        AuditAction.KPI_REMINDER_REVOKED, unit=actor.unit_id, actor=actor, record=event.record,
        event=str(event.pk),
    )
    return revocation


def valid_reminder_count(record, subject_user_id, cutoff=None):
    """Non-revoked events only (revocation lowers preview counts — KPI-CALC-21)."""
    qs = KpiReminderEvent.objects.filter(
        record=record, subject_user_id=subject_user_id, revocation__isnull=True
    )
    if cutoff is not None:
        qs = qs.filter(issued_at__lte=cutoff)
    return qs.count()
