from .queries import actionable, visible_notifications


def unread_count(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_business_user:
        return {}
    return {
        "unread_notifications": actionable(visible_notifications(user)).filter(read_at__isnull=True).count()
    }
