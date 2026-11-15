from .queries import actionable, panel_context, visible_notifications


def unread_count(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_business_user:
        return {}
    ctx = {
        "unread_notifications": actionable(visible_notifications(user)).filter(read_at__isnull=True).count()
    }
    if request.GET.get("notif") == "open":  # no-JS fallback: render the header dropdown already open
        ctx.update(notif_open=True, **panel_context(user, request.GET.get("notif_tab", "pending")))
    return ctx
