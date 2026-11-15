from apps.records import policies
from apps.records.models import RecordStatus

from .models import Notification


def visible_notifications(user):
    """Recipient-only AND the recipient must still be allowed to see the record (no leak after removal)."""
    if not getattr(user, "is_business_user", False):
        return Notification.objects.none()
    return Notification.objects.filter(
        recipient=user, unit_id=user.unit_id, record__in=policies.visible_records_queryset(user)
    )


def actionable(qs):
    return qs.filter(resolved_at__isnull=True, record__status=RecordStatus.OPEN)
