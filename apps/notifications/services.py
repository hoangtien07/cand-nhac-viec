"""In-web deadline reminders (ARCHITECTURE §6). No email/SMS/push."""

import datetime
import logging

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

from apps.audit.models import AuditAction
from apps.audit.services import audit_append
from apps.records.models import RecordAssignee, RecordStatus, WorkRecord
from apps.records.timeutils import VN_TZ, db_now, local_date

from .models import Notification, NotificationType

log = logging.getLogger("apps.notifications")


def resolve_record_notifications(record, *, actor=None, recipient_ids=None, reason):
    """Mark pending reminders resolved (history kept). Caller holds the record lock."""
    qs = Notification.objects.filter(record=record, resolved_at__isnull=True)
    if recipient_ids is not None:
        qs = qs.filter(recipient_id__in=list(recipient_ids))
    count = qs.update(resolved_at=Now())
    if count:
        audit_append(
            AuditAction.NOTIFICATION_RESOLVED,
            unit=record.unit_id,
            actor=actor,
            record=record,
            reference_no=record.reference_no,
            count=count,
            reason=reason,
        )
    return count


def _reminder_type(today, due_at, now):
    due_day = local_date(due_at)
    if now > due_at:
        return NotificationType.OVERDUE
    if today == due_day:
        return NotificationType.DUE_TODAY
    if today >= due_day - datetime.timedelta(days=settings.POCKETOPS_DUE_SOON_DAYS):
        return NotificationType.DUE_SOON
    return None


def _recipients(record, ntype):
    users = {
        a.user
        for a in RecordAssignee.objects.filter(record=record, is_active=True).select_related("user")
        if a.user.is_active and a.user.unit_id == record.unit_id
    }
    if ntype == NotificationType.OVERDUE:
        manager = record.owner_department.manager
        if manager and manager.is_active and manager.unit_id == record.unit_id and manager.is_business_user:
            users.add(manager)
    return users


def remind_record(record_id, now=None):
    """Create today's reminders for one record under its row lock. Returns number created."""
    with transaction.atomic():
        record = (
            WorkRecord.objects.select_for_update(of=("self",))
            .select_related("owner_department__manager")
            .filter(pk=record_id)
            .first()
        )
        if record is None or record.status != RecordStatus.OPEN or record.archived_at is not None:
            return 0
        now = now or db_now()
        today = local_date(now)
        ntype = _reminder_type(today, record.due_at, now)
        if ntype is None:
            return 0
        created = 0
        for user in _recipients(record, ntype):
            key = Notification.make_dedupe_key(record.pk, ntype, today, user.pk)
            _, was_created = Notification.objects.get_or_create(
                dedupe_key=key,
                defaults=dict(
                    unit_id=record.unit_id, record=record, recipient=user, type=ntype, reminder_bucket=today
                ),
            )
            created += int(was_created)
        if created:
            audit_append(
                AuditAction.REMINDER_GENERATED,
                unit=record.unit_id,
                record=record,
                reference_no=record.reference_no,
                type=ntype,
                bucket=today.isoformat(),
                count=created,
            )
        return created


def run_due_reminders(now=None, force=False):
    now = now or db_now()
    if not force and now.astimezone(VN_TZ).hour < settings.POCKETOPS_REMINDER_EARLIEST_HOUR:
        return {"skipped": True, "created": 0, "records": 0}
    horizon = datetime.datetime.combine(
        local_date(now) + datetime.timedelta(days=settings.POCKETOPS_DUE_SOON_DAYS + 1),
        datetime.time.min,
        tzinfo=VN_TZ,
    )
    ids = list(
        WorkRecord.objects.filter(
            status=RecordStatus.OPEN,
            due_at__lt=horizon,
            unit__is_active=True,
            archived_at__isnull=True,
        ).values_list("pk", flat=True)
    )
    created = sum(remind_record(pk, now=now) for pk in ids)
    log.info("send_due_reminders records=%s created=%s", len(ids), created)
    return {"skipped": False, "created": created, "records": len(ids)}
