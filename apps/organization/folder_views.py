"""Folder browsing and sharing UI. All mutations are POST + service layer + re-checked under locks."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.records import policies as record_policies
from apps.records.models import RecordShare, WorkRecord
from apps.records.queries import attach_state
from apps.records.timeutils import db_now

from . import folder_policies as policies
from . import folder_services as services
from .folder_forms import (
    FolderCreateForm,
    FolderGrantForm,
    FolderRenameForm,
    RecordFolderForm,
    RecordShareForm,
)
from .models import FolderGrant, WorkFolder

BUSINESS_DENIED = "Tài khoản quản trị kỹ thuật không được xem hồ sơ nghiệp vụ."

TABS = {
    "mine": "Của phòng tôi",
    "shared": "Được chia sẻ với tôi",
    "all": "Tất cả được phép xem",
}


def _require_business(user):
    if not user.is_business_user:
        raise PermissionDenied(BUSINESS_DENIED)


def _visible_folder(user, pk):
    folder = (
        policies.visible_folders_queryset(user)
        .select_related("owner_department", "created_by")
        .filter(pk=pk)
        .first()
    )
    if folder is None:
        raise Http404
    return folder


def _annotate_counts(user, qs):
    """Record counts are scoped to what the viewer may see — never the raw folder total."""
    visible = record_policies.visible_records_queryset(user).filter(folder=OuterRef("pk"))
    members = FolderGrant.objects.filter(folder=OuterRef("pk"), revoked_at__isnull=True)
    return qs.annotate(
        record_count=Count("records", filter=Q(Exists(visible)), distinct=True),
        member_count=Count("grants", filter=Q(Exists(members)), distinct=True),
    )


@require_GET
def index(request):
    user = request.user
    _require_business(user)
    tab = request.GET.get("tab", "mine")
    if tab not in TABS:
        tab = "mine"
    qs = policies.visible_folders_queryset(user).select_related("owner_department")
    if tab == "mine":
        if user.department_id:
            qs = qs.filter(owner_department_id=user.department_id)
        else:
            qs = qs.none()
    elif tab == "shared":
        qs = qs.filter(
            Exists(FolderGrant.objects.filter(folder=OuterRef("pk"), user=user, revoked_at__isnull=True))
        )
    folders = _annotate_counts(user, qs)
    can_create = record_policies.creatable_departments(user).exists()
    return render(
        request,
        "folders/index.html",
        {"folders": folders, "tab": tab, "tabs": TABS, "can_create": can_create},
    )


@require_GET
def detail(request, pk):
    user = request.user
    _require_business(user)
    folder = _visible_folder(user, pk)
    now = db_now()
    records = (
        record_policies.visible_records_queryset(user)
        .filter(folder=folder)
        .select_related("owner_department", "assigner")
        .order_by("status", "due_at")
    )
    page = Paginator(records, 25).get_page(request.GET.get("page"))
    page.object_list = attach_state(page.object_list, now)
    prev_href = f"?page={page.previous_page_number()}" if page.has_previous() else ""
    next_href = f"?page={page.next_page_number()}" if page.has_next() else ""
    grants = (
        FolderGrant.objects.filter(folder=folder, revoked_at__isnull=True)
        .select_related("user__department", "granted_by")
        .order_by("user__full_name")
    )
    can_manage = policies.can_manage_folder_grants(user, folder)
    ctx = {
        "folder": folder,
        "page": page,
        "grants": grants,
        "can_manage": can_manage,
        "can_create_in_folder": policies.can_create_record_in_folder(user, folder),
        "my_role": _my_folder_role(user, folder),
        "prev_href": prev_href,
        "next_href": next_href,
    }
    if can_manage:
        ctx["grant_form"] = FolderGrantForm(user, folder)
        ctx["rename_form"] = FolderRenameForm(initial={"name": folder.name})
    return render(request, "folders/detail.html", ctx)


def _my_folder_role(user, folder):
    g = FolderGrant.objects.filter(folder=folder, user=user, revoked_at__isnull=True).first()
    return g.get_role_display() if g else None


@require_http_methods(["GET", "POST"])
def create(request):
    user = request.user
    _require_business(user)
    if not record_policies.creatable_departments(user).exists():
        raise PermissionDenied("Bạn không có quyền tạo nhóm hồ sơ.")
    form = FolderCreateForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            folder = services.create_folder(
                user,
                name=form.cleaned_data["name"],
                owner_department=form.cleaned_data["owner_department"],
                description_short=form.cleaned_data["description_short"],
            )
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f"Đã tạo nhóm hồ sơ {folder.name}.")
            return redirect("folders:detail", pk=folder.pk)
    return render(
        request,
        "folders/create.html",
        {"form": form},
        status=400 if request.method == "POST" and form.errors else 200,
    )


def _first_error(form, fallback="Thao tác chưa được thực hiện; vui lòng kiểm tra lại."):
    for errs in form.errors.values():
        if errs:
            return errs[0]
    return fallback


def _mutate(request, pk, make_form, action, ok_message, allowed=None):
    """POST -> service -> redirect. Service re-checks everything under row locks."""
    user = request.user
    _require_business(user)
    folder = _visible_folder(user, pk)
    if allowed is not None:
        record_policies.require(allowed(user, folder))
    form = make_form(user, folder)
    if form.is_valid():
        try:
            action(user, folder, form.cleaned_data)
        except (WorkFolder.DoesNotExist, WorkRecord.DoesNotExist):
            raise Http404 from None
        except PermissionDenied:
            raise
        except ValidationError as e:
            messages.error(request, getattr(e, "messages", [str(e)])[0])
        else:
            messages.success(request, ok_message)
            return redirect("folders:detail", pk=folder.pk)
    else:
        messages.error(request, _first_error(form))
    return redirect("folders:detail", pk=folder.pk)


@require_POST
def rename(request, pk):
    return _mutate(
        request,
        pk,
        lambda u, f: FolderRenameForm(request.POST),
        lambda u, f, cd: services.rename_folder(u, f.pk, cd["name"]),
        "Đã đổi tên nhóm hồ sơ.",
        allowed=policies.can_manage_folder,
    )


@require_POST
def grant(request, pk):
    return _mutate(
        request,
        pk,
        lambda u, f: FolderGrantForm(u, f, request.POST),
        lambda u, f, cd: services.grant_folder(u, f.pk, cd["user"].pk, cd["role"]),
        "Đã thêm thành viên vào nhóm hồ sơ.",
        allowed=policies.can_manage_folder_grants,
    )


@require_POST
def revoke(request, pk, grant_id):
    user = request.user
    _require_business(user)
    _visible_folder(user, pk)  # 404 for out-of-scope folders
    try:
        services.revoke_folder_grant(user, grant_id)
    except (FolderGrant.DoesNotExist, WorkFolder.DoesNotExist):
        raise Http404 from None
    except PermissionDenied:
        raise
    messages.success(request, "Đã thu hồi quyền thành viên nhóm.")
    return redirect("folders:detail", pk=pk)


# --- Record-level sharing / filing (mounted under /ho-so/<pk>/ in records urls) ---


def _visible_record(user, pk):
    record = (
        record_policies.visible_records_queryset(user)
        .select_related("owner_department", "folder")
        .filter(pk=pk)
        .first()
    )
    if record is None:
        raise Http404
    return record


@require_POST
def share_record(request, pk):
    user = request.user
    _require_business(user)
    record = _visible_record(user, pk)
    if not record_policies.can_share_record(user, record):
        raise PermissionDenied("Bạn không có quyền chia sẻ hồ sơ này.")
    form = RecordShareForm(user, record, request.POST)
    if form.is_valid():
        try:
            services.share_record(user, record.pk, form.cleaned_data["user"].pk)
            messages.success(request, "Đã chia sẻ quyền xem hồ sơ.")
        except ValidationError as e:
            messages.error(request, getattr(e, "messages", [str(e)])[0])
    return redirect("records:detail", pk=record.pk)


@require_POST
def unshare_record(request, pk, share_id):
    user = request.user
    _require_business(user)
    _visible_record(user, pk)
    try:
        services.revoke_record_share(user, share_id)
    except (RecordShare.DoesNotExist, WorkRecord.DoesNotExist):
        raise Http404 from None
    messages.success(request, "Đã thu hồi quyền chia sẻ hồ sơ.")
    return redirect("records:detail", pk=pk)


@require_POST
def set_folder(request, pk):
    user = request.user
    _require_business(user)
    record = _visible_record(user, pk)
    if not record_policies.manages_record(user, record):
        raise PermissionDenied("Bạn không có quyền đổi nhóm hồ sơ của hồ sơ này.")
    form = RecordFolderForm(user, record, request.POST)
    if form.is_valid():
        dest = form.cleaned_data["folder"]
        try:
            services.move_record(user, record.pk, dest.pk if dest else None)
            messages.success(request, "Đã cập nhật nhóm hồ sơ của hồ sơ.")
        except (WorkFolder.DoesNotExist, WorkRecord.DoesNotExist):
            raise Http404 from None
        except ValidationError as e:
            messages.error(request, getattr(e, "messages", [str(e)])[0])
    return redirect("records:detail", pk=record.pk)
