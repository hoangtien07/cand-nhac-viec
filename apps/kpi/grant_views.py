"""Grant management screens (PLAN §7.2 /quan-tri/kpi-quyen/) — grant metadata only, no scores."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import policies, services
from .forms import GrantForm
from .models import GrantScope, KpiCapabilityGrant
from .views import kpi_view


@kpi_view
def grant_list(request):
    policies.require(policies.can_manage_grants(request.user))
    grants = (
        KpiCapabilityGrant.objects.filter(unit_id=request.user.unit_id)
        .select_related("user", "department", "granted_by")
    )
    form = GrantForm(request.POST or None, unit=request.user.unit)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.grant_capability(
                request.user,
                user=d["user"], capability=d["capability"], scope=d["scope"],
                department=d.get("department"), approved_by=d.get("approved_by"),
                reason=d["reason"],
            )
            messages.success(request, "Đã cấp quyền KPI.")
            return redirect("kpi_admin:grant_list")
        except (ValidationError, PermissionDenied) as e:
            form.add_error(None, e)
    return render(
        request, "kpi/grant_list.html",
        {"grants": grants, "form": form, "GrantScope": GrantScope},
    )


@kpi_view
@require_POST
def grant_revoke(request, grant_id):
    policies.require(policies.can_manage_grants(request.user))
    get_object_or_404(KpiCapabilityGrant, pk=grant_id, unit_id=request.user.unit_id)
    services.revoke_capability(request.user, grant_id)
    messages.success(request, "Đã thu hồi quyền.")
    return redirect("kpi_admin:grant_list")
