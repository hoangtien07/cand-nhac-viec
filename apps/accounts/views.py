from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET

from apps.audit.models import AuditAction
from apps.audit.services import audit_append

from .forms import LoginForm


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@require_GET
def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


@require_GET
def profile(request):
    """Read-only identity/org info; role, unit and department are managed by the technical admin."""
    return render(request, "accounts/profile.html")


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        if user.unit_id:
            audit_append(
                AuditAction.USER_CHANGED,
                unit=user.unit_id,
                actor=user,
                user=str(user.pk),
                change="password_self_service",
            )
        messages.success(self.request, "Đã đổi mật khẩu.")
        return response
