"""Home dashboard dataset. Starts from the policy-scoped queryset; never widens scope."""

import calendar
import datetime
import re

from django.core.paginator import Paginator
from django.db.models import Case, F, Prefetch, Q, Value, When
from django.http import QueryDict
from django.urls import reverse

from apps.notifications.queries import actionable, visible_notifications
from apps.organization.models import Department

from . import policies
from .codes import normalize_code
from .context_processors import initials
from .models import RecordAssignee, RecordStatus, ResultReference, WorkRecord
from .queries import attach_state, deadline_state, due_soon, due_soon_cutoff, overdue
from .timeutils import VN_TZ, local_date
from .ui_state import filter_created_in_work_year, work_year_bounds

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


TONE_PRIORITY = {"overdue": 0, "due_soon": 1, "open": 2, "done": 3}
TONE_LABEL = {
    "overdue": "có hồ sơ quá hạn",
    "due_soon": "có hồ sơ sắp đến hạn",
    "open": "có hạn xử lý",
    "done": "đã hoàn thành",
}


def parse_month(value, year):
    match = re.fullmatch(r"([0-9]{4})-([0-9]{2})", value or "")
    if match and int(match[1]) == year and 1 <= int(match[2]) <= 12:
        return int(match[2])
    return None


def _month_start(year, month):
    return datetime.datetime(year, month, 1, tzinfo=VN_TZ)


def deadline_tones(records_qs, year, month, now):
    """{local due date: most urgent derived state} for one month; one query."""
    start = _month_start(year, month)
    end = _month_start(year + month // 12, month % 12 + 1)
    tones = {}
    for rec in records_qs.filter(due_at__gte=start, due_at__lt=end).only("pk", "status", "due_at"):
        day, tone = local_date(rec.due_at), deadline_state(rec, now)
        if day not in tones or TONE_PRIORITY[tone] < TONE_PRIORITY[tones[day]]:
            tones[day] = tone
    return tones


def build_calendar(year, month, tones, today, state):
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row = []
        for day in week:
            in_month = day.month == month
            tone = tones.get(day) if in_month else None
            row.append(
                {
                    "date": day,
                    "in_month": in_month,
                    "is_today": day == today,
                    "has_deadline": bool(tone),
                    "tone": tone or "",
                    "tone_label": TONE_LABEL.get(tone, ""),
                    "href": query_string(state, due=day.isoformat(), month=f"{year}-{month:02d}", page="")
                    if tone
                    else "",
                }
            )
        weeks.append(row)
    nav = {**state, "due": "", "page": ""}
    return {
        "calendar_weeks": weeks,
        "calendar_label": f"Tháng {month}, {year}",
        "calendar_month": (year, month),
        "calendar_prev_href": query_string(nav, month=f"{year}-{month - 1:02d}") if month > 1 else "",
        "calendar_next_href": query_string(nav, month=f"{year}-{month + 1:02d}") if month < 12 else "",
    }


def _reminder_phrase(record, today):
    due_day = local_date(record.due_at)
    delta = (due_day - today).days
    if delta < 0:
        return "overdue", f"đã quá hạn {-delta} ngày"
    if delta == 0:
        return "due_soon", "đến hạn hôm nay"
    return ("due_soon" if delta <= 1 else "open"), f"đến hạn sau {delta} ngày"


def reminders_for(user, year, now, limit=3):
    """Actionable in-web reminders of THIS recipient, still-visible records only, one per record."""
    start, end = work_year_bounds(year)
    qs = (
        actionable(visible_notifications(user))
        .filter(record__created_at__gte=start, record__created_at__lt=end)
        .select_related("record")
        .order_by("-created_at", "pk")
    )
    today = local_date(now)
    items, seen = [], set()
    for n in qs[:50]:
        if n.record_id in seen:
            continue
        seen.add(n.record_id)
        n.tone, n.phrase = _reminder_phrase(n.record, today)
        items.append(n)
        if len(items) == limit:
            break
    return items, qs.values("record_id").distinct().count()


def quick_actions(user):
    """Shortcuts the backend actually permits; disabled entries are never rendered."""
    dash = reverse("dashboard")
    actions = [
        (
            "Tạo hồ sơ công việc",
            "plus-square",
            reverse("records:create"),
            policies.creatable_departments(user).exists(),
        ),
        ("Danh sách hồ sơ", "layers", reverse("records:list"), user.is_business_user),
        (
            "Nộp kết quả (số hiệu)",
            "upload",
            dash + query_string({}, tab="all") + "#dashboard-work",
            user.is_business_user,
        ),
        ("Báo cáo thống kê", "bar-chart", reverse("reports:report"), policies.can_view_reports(user)),
        ("Thông báo", "bell", reverse("notifications:inbox"), user.is_business_user),
        ("Quản lý người dùng", "users", reverse("adminpanel:home"), user.is_sys_admin),
    ]
    return [{"label": a, "icon": i, "href": h, "enabled": bool(e)} for a, i, h, e in actions if e]


def get_dashboard_data(*, user, year, tab, q, page_number, now, department="", due="", month=""):
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

    month_no = parse_month(month, year)
    state = {
        "tab": "" if tab == "all" else tab,
        "q": q,
        "department": str(dept.pk) if dept else "",
        "due": due_day.isoformat() if due_day else "",
        "month": f"{year}-{month_no:02d}" if month_no else "",
    }
    path = reverse("dashboard")
    today = local_date(now)
    cal_month = month_no or today.month
    reminders, reminder_count = reminders_for(user, year, now)
    return {
        **build_calendar(year, cal_month, deadline_tones(base, year, cal_month, now), today, state),
        "reminders": reminders,
        "reminder_count": reminder_count,
        "today": today,
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
        "reset_href": path + query_string({"tab": state["tab"], "month": state["month"]}),
        "can_create": policies.creatable_departments(user).exists(),
        "quick_actions": quick_actions(user),
    }
