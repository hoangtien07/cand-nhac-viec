"""Derived deadline state (never stored): overdue = OPEN and now > due_at."""

import datetime

from django.conf import settings

from .models import RecordStatus
from .timeutils import VN_TZ, local_date


def due_soon_cutoff(now):
    """End of the 'due soon' window: end of (today + DUE_SOON_DAYS) local time."""
    day = local_date(now) + datetime.timedelta(days=settings.POCKETOPS_DUE_SOON_DAYS + 1)
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=VN_TZ)


def overdue(qs, now):
    return qs.filter(status=RecordStatus.OPEN, due_at__lt=now)


def due_soon(qs, now):
    return qs.filter(status=RecordStatus.OPEN, due_at__gte=now, due_at__lt=due_soon_cutoff(now))


def deadline_state(record, now):
    if record.status == RecordStatus.DONE:
        return "done"
    if record.due_at < now:
        return "overdue"
    if record.due_at < due_soon_cutoff(now):
        return "due_soon"
    return "open"


def attach_state(records, now):
    records = list(records)
    for r in records:
        r.deadline_state = deadline_state(r, now)
    return records
