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


def panel_context(user, tab="pending", limit=10):
    """Data for the header notification dropdown (recipient-only, still-visible records)."""
    tab = "all" if tab == "all" else "pending"
    base = visible_notifications(user).select_related("record", "record__owner_department")
    pending = actionable(base)
    items = list((pending if tab == "pending" else base).order_by("-created_at", "pk")[: limit + 1])
    return {
        "notif_tab": tab,
        "notif_items": items[:limit],
        "notif_more": len(items) > limit,
        "notif_pending_count": pending.count(),
    }
