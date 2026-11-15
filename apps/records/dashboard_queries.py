"""Home dashboard dataset. Starts from the policy-scoped queryset; never widens scope."""

import datetime

from django.core.paginator import Paginator
from django.db.models import Case, F, Prefetch, Q, Value, When
from django.http import QueryDict
from django.urls import reverse

from apps.organization.models import Department

from . import policies
from .codes import normalize_code
from .context_processors import initials
from .models import RecordAssignee, RecordStatus, ResultReference, WorkRecord
from .queries import attach_state, due_soon, due_soon_cutoff, overdue
from .timeutils import VN_TZ
from .ui_state import filter_created_in_work_year

TABS = {
    "all": "Tất cả",
    "overdue": "Quá hạn",
    "due_soon": "Sắp đến hạn",
    "processing": "Đang xử lý",
    "done": "Hoàn thành",
}
PAGE_SIZE = 8


def assigned_records(user, year):
    """Records where `user` is an active assignee, inside policy scope, created in `year` (VN)."""
    scoped = policies.visible_records_queryset(user).filter(assignees__user=user, assignees__is_active=True)
    scoped = filter_created_in_work_year(scoped, year)
    return WorkRecord.objects.filter(pk__in=scoped.values("pk"))


def filter_dashboard_search(qs, q):
    """Search by original reference or result code, restricted to the rows already in `qs`."""
    q = (q or "").strip()
    if not q:
        return qs
    try:
        needle = normalize_code(q)
    except ValueError:
        needle = q.casefold()
    result_match = ResultReference.objects.filter(normalized_code__contains=needle).values("record_id")
    return qs.filter(Q(reference_no_normalized__contains=needle) | Q(pk__in=result_match))


def partition(qs, tab, now):
    if tab == "overdue":
        return overdue(qs, now)
    if tab == "due_soon":
        return due_soon(qs, now)
    if tab == "processing":
        return qs.filter(status=RecordStatus.OPEN, due_at__gte=due_soon_cutoff(now))
    if tab == "done":
        return qs.filter(status=RecordStatus.DONE)
    return qs


def order_for_work(qs, now):
    cutoff = due_soon_cutoff(now)
    group = Case(
        When(status=RecordStatus.DONE, then=Value(3)),
        When(due_at__lt=now, then=Value(0)),
        When(due_at__lt=cutoff, then=Value(1)),
        default=Value(2),
    )
    return qs.annotate(
        _group=group,
        _open_due=Case(When(status=RecordStatus.OPEN, then=F("due_at"))),
        _done_at=Case(When(status=RecordStatus.DONE, then=F("completed_at"))),
    ).order_by("_group", F("_open_due").asc(nulls_last=True), F("_done_at").desc(nulls_last=True), "pk")


def query_string(state, **changes):
    qd = QueryDict(mutable=True)
    for key, value in {**state, **changes}.items():
        if value not in (None, ""):
            qd[key] = str(value)
    encoded = qd.urlencode()
    return f"?{encoded}" if encoded else "?"


def parse_due(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _filter_due_day(qs, day):
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=VN_TZ)
    return qs.filter(due_at__gte=start, due_at__lt=start + datetime.timedelta(days=1))


def get_dashboard_data(*, user, year, tab, q, page_number, now, department="", due=""):
    tab = tab if tab in TABS else "all"
    q = (q or "").strip()[:64]
    base = assigned_records(user, year)
    counts = {key: partition(base, key, now).count() for key in TABS}

    departments = list(Department.objects.filter(id__in=base.values("owner_department_id")).order_by("name"))
    dept = next((d for d in departments if str(d.pk) == department), None)
    due_day = parse_due(due)

    rows = filter_dashboard_search(partition(base, tab, now), q)
    if dept:
        rows = rows.filter(owner_department=dept)
    if due_day:
        rows = _filter_due_day(rows, due_day)
    rows = order_for_work(rows, now).select_related("owner_department", "assigner")
    rows = rows.prefetch_related(
        Prefetch(
            "assignees",
            queryset=RecordAssignee.objects.filter(is_active=True)
            .select_related("user")
            .order_by("created_at"),
            to_attr="active_assignees",
        )
    )
    page = Paginator(rows, PAGE_SIZE).get_page(page_number)
    page.object_list = attach_state(page.object_list, now)
    for record in page.object_list:
        record.people = [(initials(a.user.full_name), a.user.full_name) for a in record.active_assignees]

    state = {
        "tab": "" if tab == "all" else tab,
        "q": q,
        "department": str(dept.pk) if dept else "",
        "due": due_day.isoformat() if due_day else "",
    }
    path = reverse("dashboard")
    return {
        "now": now,
        "year": year,
        "counts": counts,
        "tab": tab,
        "tab_label": TABS[tab],
        "q": q,
        "department": state["department"],
        "departments": departments,
        "due_day": due_day,
        "page": page,
        "state_query": query_string(state),
        "tab_links": [
            {
                "key": key,
                "label": label,
                "count": counts[key],
                "active": key == tab,
                "href": path + query_string(state, tab="" if key == "all" else key),
            }
            for key, label in TABS.items()
        ],
        "kpi_hrefs": {key: path + query_string({}, tab=key) for key in TABS},
        "prev_href": query_string(state, page=page.previous_page_number()) if page.has_previous() else "",
        "next_href": query_string(state, page=page.next_page_number()) if page.has_next() else "",
        "has_filters": bool(q or dept or due_day),
        "reset_href": path + query_string({"tab": state["tab"]}),
        "can_create": policies.creatable_departments(user).exists(),
    }
