from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_htmx.http import HttpResponseClientRedirect

from apps.accounts.models import User
from apps.audit.models import AuditEvent

from . import policies, services
from .codes import normalize_code
from .forms import (
    AssignmentForm,
    DeadlineForm,
    RecordCreateForm,
    RecordFilterForm,
    SubmitResultForm,
    WatchersForm,
)
from .models import RecordAssignee, RecordStatus, RecordWatcher, ResultReference, WorkRecord
from .queries import attach_state, due_soon, overdue
from .timeutils import db_now, local_date

BUSINESS_DENIED = "Tài khoản quản trị kỹ thuật không được xem hồ sơ nghiệp vụ."


def _require_business(user):
    if not user.is_business_user:
        raise PermissionDenied(BUSINESS_DENIED)


def _base_qs(user):
    return policies.visible_records_queryset(user).select_related("owner_department", "assigner")


def _get_visible(user, pk):
    try:
        return _base_qs(user).get(pk=pk)
    except (WorkRecord.DoesNotExist, ValidationError):
        raise Http404 from None


@require_GET
def dashboard(request):
    user = request.user
    if user.is_sys_admin:
        return redirect("adminpanel:home")
    _require_business(user)
    now = db_now()
    mine = _base_qs(user).filter(assignees__user=user, assignees__is_active=True)
    open_mine = mine.filter(status=RecordStatus.OPEN)
    ctx = {
        "now": now,
        "overdue": attach_state(overdue(open_mine, now).order_by("due_at")[:50], now),
        "due_soon": attach_state(due_soon(open_mine, now).order_by("due_at")[:50], now),
        "other_open": attach_state(
            open_mine.exclude(pk__in=overdue(open_mine, now))
            .exclude(pk__in=due_soon(open_mine, now))
            .order_by("due_at")[:50],
            now,
        ),
        "recent_done": attach_state(
            mine.filter(status=RecordStatus.DONE).order_by("-completed_at")[:10], now
        ),
        "assigned_by_me": attach_state(
            _base_qs(user)
            .filter(Q(assigner=user) | Q(created_by=user), status=RecordStatus.OPEN)
            .order_by("due_at")[:20],
            now,
        ),
        "can_create": policies.creatable_departments(user).exists(),
    }
    return render(request, "records/dashboard.html", ctx)


@require_GET
def record_list(request):
    user = request.user
    _require_business(user)
    now = db_now()
    form = RecordFilterForm(user, request.GET or None)
    qs = _base_qs(user)
    if form.is_valid():
        q = form.cleaned_data.get("q")
        if q:
            try:
                needle = normalize_code(q)
            except ValueError:
                needle = q.strip().casefold()
            result_match = ResultReference.objects.filter(normalized_code__contains=needle).values(
                "record_id"
            )
            qs = qs.filter(Q(reference_no_normalized__contains=needle) | Q(pk__in=result_match))
        if form.cleaned_data.get("department"):
            qs = qs.filter(owner_department=form.cleaned_data["department"])
        status = form.cleaned_data.get("status")
        if status == "OPEN":
            qs = qs.filter(status=RecordStatus.OPEN)
        elif status == "DONE":
            qs = qs.filter(status=RecordStatus.DONE)
        elif status == "OVERDUE":
            qs = overdue(qs, now)
        elif status == "DUE_SOON":
            qs = due_soon(qs, now)
    page = Paginator(qs.order_by("status", "due_at"), 25).get_page(request.GET.get("page"))
    page.object_list = attach_state(page.object_list, now)
    ctx = {"form": form, "page": page, "can_create": policies.creatable_departments(user).exists()}
    template = "records/_list_table.html" if request.htmx else "records/list.html"
    return render(request, template, ctx)


@require_http_methods(["GET", "POST"])
def record_create(request):
    user = request.user
    _require_business(user)
    if not policies.creatable_departments(user).exists():
        raise PermissionDenied("Bạn không có quyền tạo hồ sơ.")
    form = RecordCreateForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            record = services.create_record(
                user,
                reference_no=cd["reference_no"],
                owner_department=cd["owner_department"],
                due_date=cd["due_date"],
                assignees=list(cd["assignees"]),
                watchers=list(cd["watchers"]),
            )
        except ValidationError as e:
            form.add_error(None, e)
        else:
            dupes = (
                _base_qs(user)
                .filter(reference_no_normalized=record.reference_no_normalized)
                .exclude(pk=record.pk)
                .count()
            )
            messages.success(request, f"Đã tạo hồ sơ {record.reference_no}.")
            if dupes:
                messages.warning(
                    request,
                    f"Lưu ý: có {dupes} hồ sơ khác cùng số hiệu trong phạm vi bạn xem. "
                    "Hãy kiểm tra phòng chủ trì và ngày tạo để phân biệt.",
                )
            return redirect("records:detail", pk=record.pk)
    return render(request, "records/create.html", {"form": form}, status=400 if form.errors else 200)


def _user_names(unit_id, ids):
    return {str(u.pk): u.full_name for u in User.objects.filter(unit_id=unit_id, pk__in=ids)}


def _audit_rows(record):
    events = list(AuditEvent.objects.filter(record=record).select_related("actor"))
    ids = set()
    for e in events:
        for key in ("before", "after", "assignees", "watchers"):
            v = e.metadata.get(key)
            if isinstance(v, list):
                ids.update(v)
    names = _user_names(record.unit_id, ids)
    for e in events:
        md = e.metadata
        if e.action in ("record.assignment_changed", "record.watchers_changed"):
            e.summary = "Trước: {} → Sau: {}".format(
                ", ".join(names.get(i, "?") for i in md.get("before", [])) or "—",
                ", ".join(names.get(i, "?") for i in md.get("after", [])) or "—",
            )
        elif e.action == "record.deadline_changed":
            e.summary = f"{md.get('before', '')} → {md.get('after', '')}"
        elif e.action in ("result.submitted", "record.completed"):
            e.summary = f"Số hiệu: {md.get('code', '')}"
        elif e.action == "record.created":
            e.summary = "Người xử lý: " + ", ".join(names.get(i, "?") for i in md.get("assignees", []))
        elif e.action in ("reminder.generated", "notification.resolved"):
            e.summary = f"{md.get('type', md.get('reason', ''))} · {md.get('count', '')} thông báo"
        else:
            e.summary = ""
    return events


def _detail_context(request, record, **extra):
    user = request.user
    now = db_now()
    attach_state([record], now)
    assignees = RecordAssignee.objects.filter(record=record).select_related("user__department")
    watchers = RecordWatcher.objects.filter(record=record).select_related("user__department")
    active_assignees = [a for a in assignees if a.is_active]
    active_watchers = [w for w in watchers if w.is_active]
    perms = {
        "can_submit": policies.can_submit_result(user, record),
        "can_assign": policies.can_manage_assignment(user, record),
        "can_watchers": policies.can_manage_watchers(user, record),
        "can_deadline": policies.can_edit_deadline(user, record),
    }
    ctx = {
        "record": record,
        "now": now,
        "assignees": active_assignees,
        "former_assignees": [a for a in assignees if not a.is_active],
        "watchers": active_watchers,
        "results": ResultReference.objects.filter(record=record).select_related("submitted_by"),
        "audit_events": _audit_rows(record) if policies.can_view_audit(user, record) else [],
        "submit_form": SubmitResultForm(),
        **perms,
    }
    if perms["can_assign"]:
        ctx["assignment_form"] = AssignmentForm(
            user, record, initial={"assignees": [a.user_id for a in active_assignees]}
        )
    if perms["can_watchers"]:
        ctx["watchers_form"] = WatchersForm(
            user, record, initial={"watchers": [w.user_id for w in active_watchers]}
        )
    if perms["can_deadline"]:
        ctx["deadline_form"] = DeadlineForm(initial={"due_date": local_date(record.due_at)})
    ctx.update(extra)
    return ctx


@require_GET
def record_detail(request, pk):
    _require_business(request.user)
    record = _get_visible(request.user, pk)
    return render(request, "records/detail.html", _detail_context(request, record))


@require_POST
def submit_result(request, pk):
    """Two-step: first POST shows a confirmation, second POST (confirm=1) performs the submit."""
    user = request.user
    _require_business(user)
    record = _get_visible(user, pk)
    if not policies.can_submit_result(user, record):
        raise PermissionDenied("Chỉ người được giao đang hoạt động mới được nộp số hiệu kết quả.")
    form = SubmitResultForm(request.POST)
    if not form.is_valid():
        ctx = {"record": record, "submit_form": form, "can_submit": True}
        return render(request, "records/_submit_form.html", ctx, status=400)
    code = form.cleaned_data["code"]
    if request.POST.get("confirm") != "1":
        return render(request, "records/submit_confirm.html", {"record": record, "code": code})
    try:
        outcome = services.submit_result_reference(user, record.pk, code)
    except WorkRecord.DoesNotExist:
        raise Http404 from None
    except ValidationError as e:
        form.add_error("code", e)
        return render(
            request,
            "records/_submit_form.html",
            {"record": record, "submit_form": form, "can_submit": True},
            status=400,
        )
    if not outcome.created:
        messages.info(
            request, f"Số hiệu {outcome.result.code} đã được nộp trước đó; không tạo bản ghi trùng."
        )
    elif outcome.completed_record:
        messages.success(request, f"Đã nộp số hiệu {code}. Hồ sơ đã HOÀN THÀNH.")
    else:
        messages.success(request, f"Đã bổ sung số hiệu {code}. Hồ sơ vẫn ở trạng thái đã hoàn thành.")
    url = reverse("records:detail", args=[record.pk])
    return HttpResponseClientRedirect(url) if request.htmx else redirect(url)


def _mutate(request, pk, form_cls, action, ok_message, form_key):
    user = request.user
    _require_business(user)
    record = _get_visible(user, pk)
    form = form_cls(user, record, request.POST) if form_cls is not DeadlineForm else form_cls(request.POST)
    if form.is_valid():
        try:
            action(user, record, form.cleaned_data)
        except WorkRecord.DoesNotExist:
            raise Http404 from None
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, ok_message)
            return redirect("records:detail", pk=record.pk)
    record.refresh_from_db()
    ctx = _detail_context(request, record, **{form_key: form})
    return render(request, "records/detail.html", ctx, status=400)


@require_POST
def update_assignment(request, pk):
    record = _get_visible(request.user, pk)
    policies.require(policies.can_manage_assignment(request.user, record))
    return _mutate(
        request,
        pk,
        AssignmentForm,
        lambda u, r, cd: services.update_assignment(u, r.pk, list(cd["assignees"])),
        "Đã cập nhật người xử lý.",
        "assignment_form",
    )


@require_POST
def update_watchers(request, pk):
    record = _get_visible(request.user, pk)
    policies.require(policies.can_manage_watchers(request.user, record))
    return _mutate(
        request,
        pk,
        WatchersForm,
        lambda u, r, cd: services.update_watchers(u, r.pk, list(cd["watchers"])),
        "Đã cập nhật người theo dõi.",
        "watchers_form",
    )


@require_POST
def update_deadline(request, pk):
    record = _get_visible(request.user, pk)
    policies.require(policies.can_edit_deadline(request.user, record))
    return _mutate(
        request,
        pk,
        DeadlineForm,
        lambda u, r, cd: services.update_deadline(u, r.pk, cd["due_date"]),
        "Đã cập nhật hạn xử lý.",
        "deadline_form",
    )
