from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models.functions import Now
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .queries import actionable, visible_notifications


def _require_business(user):
    if not user.is_business_user:
        raise PermissionDenied("Tài khoản quản trị kỹ thuật không có thông báo nghiệp vụ.")


@require_GET
def inbox(request):
    _require_business(request.user)
    tab = request.GET.get("tab", "pending")
    qs = visible_notifications(request.user).select_related("record", "record__owner_department")
    qs = actionable(qs) if tab == "pending" else qs
    page = Paginator(qs.order_by("-created_at"), 30).get_page(request.GET.get("page"))
    return render(request, "notifications/inbox.html", {"page": page, "tab": tab})


@require_POST
def mark_read(request, pk):
    _require_business(request.user)
    n = get_object_or_404(visible_notifications(request.user), pk=pk)
    if n.read_at is None:
        type(n).objects.filter(pk=n.pk, read_at__isnull=True).update(read_at=Now())
    n.refresh_from_db()
    if request.htmx:
        return render(request, "notifications/_item.html", {"n": n})
    return redirect("notifications:inbox")


@require_POST
def mark_all_read(request):
    _require_business(request.user)
    visible_notifications(request.user).filter(read_at__isnull=True).update(read_at=Now())
    return redirect("notifications:inbox")


@require_GET
def badge(request):
    return render(request, "notifications/_badge.html")
