from django.core.exceptions import PermissionDenied
from django.db.models.functions import Now
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .queries import panel_context, visible_notifications


def _require_business(user):
    if not user.is_business_user:
        raise PermissionDenied("Tài khoản quản trị kỹ thuật không có thông báo nghiệp vụ.")


def _back_to_dropdown(tab="pending"):
    return redirect(reverse("dashboard") + "?notif=open" + ("&notif_tab=all" if tab == "all" else ""))


@require_GET
def inbox(request):
    """No standalone page: HTMX fragment for the header dropdown; plain GET opens the dropdown."""
    _require_business(request.user)
    tab = request.GET.get("tab", "pending")
    if not request.htmx:
        return _back_to_dropdown(tab)
    return render(request, "notifications/_panel.html", panel_context(request.user, tab))


@require_POST
def mark_read(request, pk):
    _require_business(request.user)
    n = get_object_or_404(
        visible_notifications(request.user).select_related("record__owner_department"), pk=pk
    )
    if n.read_at is None:
        type(n).objects.filter(pk=n.pk, read_at__isnull=True).update(read_at=Now())
    n.refresh_from_db()
    if request.htmx:
        return render(request, "notifications/_item.html", {"n": n, "oob": True})
    return _back_to_dropdown()


@require_POST
def mark_all_read(request):
    _require_business(request.user)
    visible_notifications(request.user).filter(read_at__isnull=True).update(read_at=Now())
    if request.htmx:
        return render(request, "notifications/_panel.html", {**panel_context(request.user), "oob": True})
    return _back_to_dropdown()


@require_GET
def badge(request):
    return render(request, "notifications/_badge.html")
