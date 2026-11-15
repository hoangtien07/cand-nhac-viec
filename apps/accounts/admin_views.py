"""Technical administration (/quan-tri/): users, roles, departments of the admin's own unit only.

SYS_ADMIN never gets business-record access from here (ARCHITECTURE §7)."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.audit.models import AuditAction
from apps.audit.services import audit_append
from apps.organization.models import Department

from .forms import AdminSetPasswordForm, DepartmentForm, UserCreateForm, UserEditForm
from .models import User


def _require_admin(user):
    if not user.is_sys_admin:
        raise PermissionDenied("Chỉ quản trị kỹ thuật được truy cập trang này.")


def home(request):
    _require_admin(request.user)
    unit_id = request.user.unit_id
    users = (
        User.objects.filter(unit_id=unit_id)
        .select_related("department")
        .order_by("department__name", "full_name")
    )
    depts = Department.objects.filter(unit_id=unit_id).select_related("manager")
    return render(request, "adminpanel/home.html", {"users": users, "departments": depts})


@require_http_methods(["GET", "POST"])
def user_create(request):
    admin = request.user
    _require_admin(admin)
    form = UserCreateForm(admin, request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save(commit=False)
            user.unit_id = admin.unit_id
            user.set_password(form.cleaned_data["password1"])
            user.save()
            audit_append(
                AuditAction.USER_CREATED,
                unit=admin.unit_id,
                actor=admin,
                user=str(user.pk),
                role=user.role,
                department=str(user.department_id),
            )
        messages.success(request, f"Đã tạo tài khoản {user.username}.")
        return redirect("adminpanel:home")
    return render(request, "adminpanel/user_form.html", {"form": form, "title": "Tạo tài khoản"})


@require_http_methods(["GET", "POST"])
def user_edit(request, pk):
    admin = request.user
    _require_admin(admin)
    target = get_object_or_404(User, pk=pk, unit_id=admin.unit_id)
    before = {"role": target.role, "department": str(target.department_id), "is_active": target.is_active}
    form = UserEditForm(admin, request.POST or None, instance=target)
    pw_form = (
        AdminSetPasswordForm(target, request.POST or None, prefix="pw")
        if "pw-password1" in request.POST
        else (AdminSetPasswordForm(target, prefix="pw"))
    )
    if request.method == "POST" and "pw-password1" in request.POST:
        if pw_form.is_valid():
            target.set_password(pw_form.cleaned_data["password1"])
            target.save(update_fields=["password"])
            audit_append(
                AuditAction.USER_CHANGED,
                unit=admin.unit_id,
                actor=admin,
                user=str(target.pk),
                change="password_reset",
            )
            messages.success(request, "Đã đặt lại mật khẩu.")
            return redirect("adminpanel:home")
        form = UserEditForm(admin, instance=target)
    elif request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            after = {"role": user.role, "department": str(user.department_id), "is_active": user.is_active}
            if before["role"] != after["role"]:
                audit_append(
                    AuditAction.USER_ROLE_CHANGED,
                    unit=admin.unit_id,
                    actor=admin,
                    user=str(user.pk),
                    before=before["role"],
                    after=after["role"],
                )
            if before != after:
                audit_append(
                    AuditAction.USER_CHANGED,
                    unit=admin.unit_id,
                    actor=admin,
                    user=str(user.pk),
                    before=before,
                    after=after,
                )
        messages.success(request, f"Đã cập nhật {user.username}.")
        return redirect("adminpanel:home")
    return render(
        request,
        "adminpanel/user_form.html",
        {"form": form, "pw_form": pw_form, "target": target, "title": f"Sửa tài khoản {target.username}"},
    )


@require_http_methods(["GET", "POST"])
def department_form(request, pk=None):
    admin = request.user
    _require_admin(admin)
    dept = get_object_or_404(Department, pk=pk, unit_id=admin.unit_id) if pk else None
    before = (
        {"name": dept.name, "manager": str(dept.manager_id), "is_active": dept.is_active} if dept else None
    )
    form = DepartmentForm(admin, request.POST or None, instance=dept)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            d = form.save(commit=False)
            d.unit_id = admin.unit_id
            d.save()
            audit_append(
                AuditAction.DEPARTMENT_CHANGED,
                unit=admin.unit_id,
                actor=admin,
                department=str(d.pk),
                before=before,
                after={"name": d.name, "manager": str(d.manager_id), "is_active": d.is_active},
            )
        messages.success(request, f"Đã lưu phòng/đội {d.name}.")
        return redirect("adminpanel:home")
    title = f"Sửa phòng/đội {dept.name}" if dept else "Tạo phòng/đội"
    return render(request, "adminpanel/department_form.html", {"form": form, "title": title})
