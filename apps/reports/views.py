from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.records import policies
from apps.records.models import RecordStatus
from apps.records.queries import due_soon_cutoff
from apps.records.timeutils import db_now
from apps.records.ui_state import filter_created_in_work_year, get_active_work_year


def report_summary(user, now, year=None):
    qs = policies.report_records_queryset(user)
    if year is not None:
        qs = filter_created_in_work_year(qs, year)
    agg = dict(
        open=Count("id", distinct=True, filter=Q(status=RecordStatus.OPEN)),
        done=Count("id", distinct=True, filter=Q(status=RecordStatus.DONE)),
        overdue=Count("id", distinct=True, filter=Q(status=RecordStatus.OPEN, due_at__lt=now)),
        due_soon=Count(
            "id",
            distinct=True,
            filter=Q(status=RecordStatus.OPEN, due_at__gte=now, due_at__lt=due_soon_cutoff(now)),
        ),
        total=Count("id", distinct=True),
    )
    totals = qs.aggregate(**agg)
    by_dept = qs.values("owner_department__name").annotate(**agg).order_by("owner_department__name")
    return totals, list(by_dept)


def _scoped_qs(user, year=None):
    qs = policies.report_records_queryset(user)
    if year is not None:
        qs = filter_created_in_work_year(qs, year)
    return qs


def _month_key(dt):
    return f"{dt.year:04d}-{dt.month:02d}"


def report_charts(qs, now, year):
    """Truthful aggregates for Chart.js, all from the authorized `qs`. Every series is also
    rendered as an HTML table — charts are progressive enhancement, not the only source."""
    months = [f"{year:04d}-{m:02d}" for m in range(1, 13)]
    created = {m: 0 for m in months}
    for row in qs.annotate(m=TruncMonth("created_at")).values("m").annotate(n=Count("id")):
        created[_month_key(row["m"])] = row["n"]
    completed = {m: 0 for m in months}
    for row in (
        qs.filter(completed_at__isnull=False)
        .annotate(m=TruncMonth("completed_at"))
        .values("m")
        .annotate(n=Count("id"))
    ):
        completed[_month_key(row["m"])] = row["n"]

    cutoff = due_soon_cutoff(now)
    # Mutually exclusive status buckets: DONE / OVERDUE / DUE_SOON / OPEN (còn hạn xa)
    status_rows = [
        ("Đã hoàn thành", qs.filter(status=RecordStatus.DONE).count()),
        ("Quá hạn", qs.filter(status=RecordStatus.OPEN, due_at__lt=now).count()),
        (
            "Sắp đến hạn",
            qs.filter(status=RecordStatus.OPEN, due_at__gte=now, due_at__lt=cutoff).count(),
        ),
        (
            "Đang xử lý",
            qs.filter(status=RecordStatus.OPEN, due_at__gte=cutoff).count(),
        ),
    ]

    by_folder = list(
        qs.filter(folder__isnull=False)
        .values("folder__name")
        .annotate(total=Count("id", distinct=True))
        .order_by("folder__name")
    )

    age = {"1-7": 0, "8-30": 0, "31-90": 0, ">90": 0}
    for due in qs.filter(status=RecordStatus.OPEN, due_at__lt=now).values_list("due_at", flat=True):
        days = (now - due).days
        if days <= 7:
            age["1-7"] += 1
        elif days <= 30:
            age["8-30"] += 1
        elif days <= 90:
            age["31-90"] += 1
        else:
            age[">90"] += 1

    return {
        "monthly": {
            "labels": months,
            "created": [created[m] for m in months],
            "completed": [completed[m] for m in months],
        },
        "status": {"labels": [r[0] for r in status_rows], "counts": [r[1] for r in status_rows]},
        "by_folder": {
            "labels": [r["folder__name"] for r in by_folder],
            "counts": [r["total"] for r in by_folder],
        },
        "overdue_age": {"labels": list(age), "counts": list(age.values())},
    }


@require_GET
def report(request):
    user = request.user
    if not policies.can_view_reports(user):
        raise PermissionDenied("Bạn không có quyền xem báo cáo nghiệp vụ.")
    now = db_now()
    year = get_active_work_year(request)
    totals, by_dept = report_summary(user, now, year=year)
    qs = _scoped_qs(user, year)
    scope = {
        "LEADER": "Toàn đơn vị",
        "DEPT_MANAGER": "Phòng/đội bạn quản lý và hồ sơ bạn tham gia",
        "OFFICER": "Hồ sơ bạn tạo, giao hoặc được giao",
    }[user.role]
    return render(
        request,
        "reports/report.html",
        {
            "totals": totals,
            "by_dept": by_dept,
            "scope": scope,
            "now": now,
            "year": year,
            "charts": report_charts(qs, now, year),
        },
    )
