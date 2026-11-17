from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_htmx.http import HttpResponseClientRedirect

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.notifications.models import NotificationType

from . import dashboard_queries, policies, services
from .forms import (
    ArchiveForm,
    AssignmentForm,
    CorrectionForm,
    DeadlineForm,
    RecordCreateForm,
    RecordEditForm,
    RecordFilterForm,
    RevokeResultForm,
    SubmitResultForm,
)
from .models import RecordAssignee, RecordStatus, ResultReference, WorkRecord
from .queries import attach_state, due_soon, overdue
from .timeutils import db_now, local_date
from .ui_state import SESSION_KEY, filter_created_in_work_year, get_active_work_year, parse_work_year

BUSINESS_DENIED = "Tài khoản quản trị kỹ thuật không được xem hồ sơ nghiệp vụ."


def _require_business(user):
    if not user.is_business_user:
        raise PermissionDenied(BUSINESS_DENIED)


def _base_qs(user):
    return policies.visible_records_queryset(user).select_related("owner_department", "assigner", "folder")


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
    g = request.GET
    data = dashboard_queries.get_dashboard_data(
        user=user,
        year=get_active_work_year(request),
        tab=g.get("tab", ""),
        q=g.get("q", ""),
        page_number=g.get("page"),
        now=db_now(),
        department=g.get("department", ""),
        due=g.get("due", ""),
        month=g.get("month", ""),
    )
    partial = request.htmx and request.htmx.target == "dashboard-work"
    return render(request, "records/_dashboard_work.html" if partial else "records/dashboard.html", data)


@require_POST
def set_work_year(request):
    """Stores the view filter only; never touches the user's unit/department or permissions."""
    _require_business(request.user)
    year = parse_work_year(request.POST.get("year"))
    if year is None:
        return HttpResponseBadRequest("Năm làm việc không hợp lệ.")
    request.session[SESSION_KEY] = year
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt.split("?", 1)[0].split("#", 1)[0])
    return redirect("dashboard")


@require_GET
def record_list(request):
    user = request.user
    _require_business(user)
    now = db_now()
    form = RecordFilterForm(user, request.GET or None)
    qs = filter_created_in_work_year(_base_qs(user), get_active_work_year(request))
    form_valid = form.is_valid()
    archived_view = form_valid and form.cleaned_data.get("status") == "ARCHIVED"
    qs = qs.filter(archived_at__isnull=not archived_view)
    if form_valid:
        qs = dashboard_queries.filter_dashboard_search(qs, form.cleaned_data.get("q"))
        if form.cleaned_data.get("department"):
            qs = qs.filter(owner_department=form.cleaned_data["department"])
        if form.cleaned_data.get("folder"):
            qs = qs.filter(folder=form.cleaned_data["folder"])
        if form.cleaned_data.get("assignee"):
            qs = qs.filter(
                assignees__user=form.cleaned_data["assignee"], assignees__is_active=True
            ).distinct()
        if form.cleaned_data.get("creator"):
            qs = qs.filter(created_by=form.cleaned_data["creator"])
        if form.cleaned_data.get("due_from"):
            qs = qs.filter(due_at__date__gte=form.cleaned_data["due_from"])
        if form.cleaned_data.get("due_to"):
            qs = qs.filter(due_at__date__lte=form.cleaned_data["due_to"])
        if form.cleaned_data.get("assigned_to_me"):
            qs = qs.filter(assignees__user=user, assignees__is_active=True).distinct()
        if form.cleaned_data.get("shared_with_me"):
            qs = qs.filter(
                Q(shares__user=user, shares__revoked_at__isnull=True)
                | Q(
                    folder__grants__user=user,
                    folder__grants__revoked_at__isnull=True,
                    folder__is_archived=False,
                )
            ).distinct()
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
    for r in page.object_list:
        r.row_can_edit = policies.can_edit_record_metadata(user, r)
        r.row_can_submit = policies.can_submit_result(user, r)
        r.row_can_archive = policies.can_archive_record(user, r)
    state = {k: v for k, v in request.GET.items() if k != "page"}
    ctx = {
        "form": form,
        "page": page,
        "can_create": policies.creatable_departments(user).exists(),
        "prev_href": dashboard_queries.query_string(state, page=page.previous_page_number())
        if page.has_previous()
        else "",
        "next_href": dashboard_queries.query_string(state, page=page.next_page_number())
        if page.has_next()
        else "",
    }
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
                description_short=cd["description_short"],
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


_RESOLVE_REASONS = {
    "record_done": "Hồ sơ đã hoàn thành",
    "assignee_removed": "Người xử lý bị thu hồi",
    "deadline_changed": "Đổi hạn xử lý",
}


def _user_names(unit_id, ids):
    return {str(u.pk): u.full_name for u in User.objects.filter(unit_id=unit_id, pk__in=ids)}


def _audit_rows(record):
    from apps.organization.models import WorkFolder

    events = list(AuditEvent.objects.filter(record=record).select_related("actor"))
    ids, folder_ids = set(), set()
    for e in events:
        for key in ("before", "after", "assignees", "watchers"):
            v = e.metadata.get(key)
            if isinstance(v, list):
                ids.update(v)
        uid = e.metadata.get("user_id")
        if isinstance(uid, str):
            ids.add(uid)
        for key in ("before_folder_id", "after_folder_id"):
            if e.metadata.get(key):
                folder_ids.add(e.metadata[key])
    names = _user_names(record.unit_id, ids)
    folder_names = {str(f.pk): f.name for f in WorkFolder.objects.filter(pk__in=folder_ids)}
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
        elif e.action == "result.corrected":
            e.summary = f"{md.get('before', '')} → {md.get('after', '')} · {md.get('reason', '')}"
        elif e.action == "result.revoked":
            e.summary = f"Số hiệu: {md.get('code', '')} · {md.get('reason', '')}"
        elif e.action == "record.updated":
            e.summary = f"{md.get('field', '')}: {md.get('before', '')} → {md.get('after', '')}"
        elif e.action == "record.archived":
            e.summary = f"Lý do: {md.get('reason', '')}"
        elif e.action == "record.restored":
            e.summary = ""
        elif e.action == "record.created":
            e.summary = "Người xử lý: " + ", ".join(names.get(i, "?") for i in md.get("assignees", []))
        elif e.action in ("record.share_added", "record.share_revoked"):
            e.summary = f"Người dùng: {names.get(md.get('user_id'), '?')}"
        elif e.action == "record.folder_moved":
            e.summary = "{} → {}".format(
                folder_names.get(md.get("before_folder_id"), "—"),
                folder_names.get(md.get("after_folder_id"), "—"),
            )
        elif e.action in ("reminder.generated", "notification.resolved"):
            label = NotificationType(md["type"]).label if md.get("type") in NotificationType.values else ""
            label = label or _RESOLVE_REASONS.get(md.get("reason"), "")
            e.summary = f"{label} · {md.get('count', '')} thông báo"
        else:
            e.summary = ""
    return events


def _access_reasons(user, record):
    """Why THIS viewer can open this record (DECISIONS §6: show the reason, never leak)."""
    from apps.organization.folder_policies import can_view_folder
    from apps.organization.models import FolderGrant

    reasons = []
    if user.role == "LEADER":
        reasons.append("Lãnh đạo đơn vị")
    if record.created_by_id == user.pk or record.assigner_id == user.pk:
        reasons.append("Bạn tạo/giao hồ sơ này")
    if record.assignees.filter(user=user, is_active=True).exists():
        reasons.append("Bạn đang được giao xử lý")
    elif record.watchers.filter(user=user, is_active=True).exists():
        reasons.append("Bạn đang theo dõi hồ sơ")
    if record.shares.filter(user=user, revoked_at__isnull=True).exists():
        reasons.append("Hồ sơ được chia sẻ trực tiếp cho bạn")
    if (
        record.folder_id
        and FolderGrant.objects.filter(
            folder_id=record.folder_id, user=user, revoked_at__isnull=True
        ).exists()
    ):
        reasons.append("Bạn là thành viên nhóm hồ sơ chứa hồ sơ này")
    elif record.owner_department_id in policies.managed_department_ids(user):
        reasons.append("Hồ sơ thuộc phòng/đội bạn quản lý")
    if not reasons:
        reasons.append("Hồ sơ thuộc phạm vi quản lý của bạn")
    return reasons, can_view_folder(user, record.folder) if record.folder_id else False


def _detail_context(request, record, **extra):
    from apps.organization.folder_forms import RecordFolderForm, RecordShareForm
    from apps.organization.folder_policies import movable_folders

    user = request.user
    now = db_now()
    attach_state([record], now)
    assignees = RecordAssignee.objects.filter(record=record).select_related("user__department")
    active_assignees = [a for a in assignees if a.is_active]
    perms = {
        "can_submit": policies.can_submit_result(user, record),
        "can_assign": policies.can_manage_assignment(user, record),
        "can_deadline": policies.can_edit_deadline(user, record),
        "can_edit": policies.can_edit_record_metadata(user, record),
        "can_archive": policies.can_archive_record(user, record),
        "can_restore": policies.can_restore_record(user, record),
    }
    can_share = policies.can_share_record(user, record)
    reasons, can_open_folder = _access_reasons(user, record)
    movable = list(movable_folders(user, record)) if policies.manages_record(user, record) else []
    results = list(
        ResultReference.objects.filter(record=record)
        .select_related("submitted_by")
        .prefetch_related("corrections__actor", "corrections__replacement")
    )
    for res in results:
        res.can_correct = policies.can_correct_result(user, record, res)
    ctx = {
        "record": record,
        "now": now,
        "assignees": active_assignees,
        "former_assignees": [a for a in assignees if not a.is_active],
        "results": results,
        "audit_events": _audit_rows(record) if policies.can_view_audit(user, record) else [],
        "submit_form": SubmitResultForm(),
        "can_share": can_share,
        "access_reasons": reasons,
        "can_open_folder": can_open_folder,
        "movable_folders": movable,
        "archive_form": ArchiveForm(),
        "correction_form": CorrectionForm(),
        "revoke_form": RevokeResultForm(),
        **perms,
    }
    if can_share:
        ctx["shares"] = (
            record.shares.filter(revoked_at__isnull=True)
            .select_related("user__department", "granted_by")
            .order_by("user__full_name")
        )
        ctx["share_form"] = RecordShareForm(user, record)
    if movable:
        ctx["folder_form"] = RecordFolderForm(user, record, initial={"folder": record.folder_id})
    if perms["can_assign"]:
        ctx["assignment_form"] = AssignmentForm(
            user, record, initial={"assignees": [a.user_id for a in active_assignees]}
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


def _fold(text):
    """Casefold + strip Vietnamese diacritics so 'ho so' matches 'hồ sơ'."""
    import unicodedata

    return "".join(
        c
        for c in unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D").casefold())
        if unicodedata.category(c) != "Mn"
    )


def _submittable_records(user, q=""):
    """Records the user may submit a result code for (same unit, active assignee, not archived).
    `q` matches reference_no or description_short, accent-insensitive."""
    qs = (
        WorkRecord.objects.filter(
            unit=user.unit,
            archived_at__isnull=True,
            assignees__user=user,
            assignees__is_active=True,
        )
        .select_related("owner_department")
        .order_by("due_at", "reference_no")
    )
    q = _fold(q).strip()
    if not q:
        return list(qs[:10])
    return [r for r in qs[:200] if q in _fold(r.reference_no) or q in _fold(r.description_short)][:10]


def quick_submit(request):
    """GET: modal pick-a-record + code form, loaded into #modal-root via HTMX.
    POST: submit the result code through the same locked service path."""
    user = request.user
    _require_business(user)
    if request.method == "GET":
        selected = None
        if rid := request.GET.get("record"):
            selected = WorkRecord.objects.filter(pk=rid).first()
            if selected is None or not policies.can_submit_result(user, selected):
                selected = None
        return render(
            request,
            "records/_quick_submit_modal.html",
            {"form": SubmitResultForm(), "selected": selected},
        )
    form = SubmitResultForm(request.POST)
    record_id = request.POST.get("record", "")
    error = None
    if form.is_valid():
        if not record_id:
            error = "Chọn một hồ sơ trong danh sách."
        else:
            try:
                outcome = services.submit_result_reference(user, record_id, form.cleaned_data["code"])
            except WorkRecord.DoesNotExist:
                error = "Không tìm thấy hồ sơ hoặc bạn không có quyền nộp kết quả."
            except ValidationError as e:
                form.add_error("code", e)
            else:
                if outcome.completed_record:
                    messages.success(request, "Đã nộp số hiệu. Hồ sơ đã HOÀN THÀNH.")
                elif outcome.created:
                    messages.success(request, "Đã bổ sung số hiệu kết quả.")
                else:
                    messages.info(request, "Số hiệu này đã được nộp trước đó; không tạo bản ghi trùng.")
                url = reverse("records:detail", args=[outcome.result.record_id]) + "#ket-qua"
                return HttpResponseClientRedirect(url) if request.htmx else redirect(url)
    if not request.htmx:
        messages.error(request, error or "Dữ liệu không hợp lệ.")
        return redirect("records:list")
    selected = WorkRecord.objects.filter(pk=record_id).first() if record_id else None
    return render(
        request,
        "records/_quick_submit_modal.html",
        {"form": form, "selected": selected, "error": error},
    )


@require_GET
def quick_submit_search(request):
    """Combobox options for the record picker (accent-insensitive q)."""
    _require_business(request.user)
    return render(
        request,
        "records/_quick_submit_options.html",
        {"records": _submittable_records(request.user, request.GET.get("q"))},
    )


@require_GET
def quick_submit_pick(request):
    """Select one record into the picker chip; clears the dropdown + search text via OOB swaps."""
    user = request.user
    _require_business(user)
    selected = None
    if rid := request.GET.get("record"):
        selected = WorkRecord.objects.filter(pk=rid).first()
        if selected is None or not policies.can_submit_result(user, selected):
            selected = None
    return render(request, "records/_quick_submit_pick.html", {"selected": selected})


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


@require_http_methods(["GET", "POST"])
def record_edit(request, pk):
    """Metadata edit page (spec §3): OPEN + managed scope only; every field change goes through
    an audited service inside ONE transaction."""
    user = request.user
    _require_business(user)
    record = _get_visible(user, pk)
    policies.require(policies.can_edit_record_metadata(user, record))
    if request.method == "POST":
        form = RecordEditForm(user, record, request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    _apply_edit(user, record, form.cleaned_data)
            except WorkRecord.DoesNotExist:
                raise Http404 from None
            except ValidationError as e:
                form.add_error(None, e)
            else:
                messages.success(request, "Đã cập nhật thông tin hồ sơ.")
                return redirect("records:detail", pk=record.pk)
    else:
        form = RecordEditForm(
            user,
            record,
            initial={
                "reference_no": record.reference_no,
                "owner_department": record.owner_department_id,
                "folder": record.folder_id,
                "due_date": local_date(record.due_at),
                "description_short": record.description_short,
                "assignees": [a.user_id for a in record.assignees.filter(is_active=True)],
            },
        )
    return render(request, "records/edit.html", {"record": record, "form": form})


def _apply_edit(user, record, cd):
    """Applies form changes through audited services. Order: folder first so an owner-dept move
    never sees a folder that belongs to the old department."""
    from apps.organization import folder_services

    new_folder = cd["folder"].pk if cd["folder"] else None
    if new_folder != record.folder_id:
        folder_services.move_record(user, record.pk, new_folder)
    if cd["reference_no"] != record.reference_no:
        services.update_reference_no(user, record.pk, cd["reference_no"])
    if cd["description_short"] != record.description_short:
        services.update_description(user, record.pk, cd["description_short"])
    if cd["owner_department"].pk != record.owner_department_id:
        services.update_owner_department(user, record.pk, cd["owner_department"])
    current = sorted(record.assignees.filter(is_active=True).values_list("user_id", flat=True))
    if sorted(u.pk for u in cd["assignees"]) != current:
        services.update_assignment(user, record.pk, list(cd["assignees"]))
    if cd["due_date"] != local_date(record.due_at):
        services.update_deadline(user, record.pk, cd["due_date"])


@require_POST
def archive_record(request, pk):
    user = request.user
    _require_business(user)
    record = _get_visible(user, pk)
    form = ArchiveForm(request.POST)
    if form.is_valid():
        try:
            services.archive_record(user, record.pk, form.cleaned_data["reason"])
        except WorkRecord.DoesNotExist:
            raise Http404 from None
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
        else:
            messages.success(request, f"Đã lưu trữ hồ sơ {record.reference_no}.")
            return redirect("records:list")
    else:
        messages.error(request, "Cần nhập lý do lưu trữ.")
    return redirect("records:detail", pk=record.pk)


@require_POST
def restore_record(request, pk):
    user = request.user
    _require_business(user)
    record = _get_visible(user, pk)
    try:
        services.restore_record(user, record.pk)
    except WorkRecord.DoesNotExist:
        raise Http404 from None
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    else:
        messages.success(request, f"Đã khôi phục hồ sơ {record.reference_no}.")
    return redirect("records:detail", pk=record.pk)


def _mutate_result(request, pk, result_id, form_cls, action):
    user = request.user
    _require_business(user)
    record = _get_visible(user, pk)
    form = form_cls(request.POST)
    if form.is_valid():
        try:
            action(user, record, form.cleaned_data)
        except ResultReference.DoesNotExist:
            raise Http404 from None
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
        else:
            messages.success(request, "Đã cập nhật số hiệu kết quả.")
    else:
        messages.error(request, "Biểu mẫu không hợp lệ.")
    return redirect(reverse("records:detail", args=[record.pk]) + "#ket-qua")


@require_POST
def correct_result(request, pk, result_id):
    return _mutate_result(
        request,
        pk,
        result_id,
        CorrectionForm,
        lambda u, r, cd: services.correct_result_reference(u, r.pk, result_id, cd["new_code"], cd["reason"]),
    )


@require_POST
def revoke_result(request, pk, result_id):
    return _mutate_result(
        request,
        pk,
        result_id,
        RevokeResultForm,
        lambda u, r, cd: services.revoke_result_reference(u, r.pk, result_id, cd["reason"]),
    )
