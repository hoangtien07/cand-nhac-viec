from decimal import Decimal

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
    # EU-05: không render thẻ/cột/bucket "Đang xử lý"; khóa `open` vẫn được tính
    # (RecordStatus.OPEN tồn tại trong DB và vẫn điều khiển quá hạn).
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


def periodic_stats(records_qs):
    """ADR-005: plan count and period count are separate metrics — a plan with 12
    deadlines is still 1 document, not 12."""
    per = records_qs.filter(periodic_plan__isnull=False)
    return {
        "plans": per.values("periodic_plan").distinct().count(),
        "periods": per.count(),
        "done_periods": per.filter(status=RecordStatus.DONE).count(),
    }


def kpi_stats(user):
    """WP7: aggregate only FINALIZED effective snapshots; officer sees own only;
    no score data at all without a score-view grant (deny by default)."""
    from apps.kpi import queries as kq
    from apps.kpi.models import EvaluationStatus
    from apps.kpi.policies import kpi_enabled

    if not kpi_enabled() or not getattr(user, "is_business_user", False):
        return None
    if kq.can_view_scores(user):
        evals = list(
            kq.scoped_evaluations(user)
            .filter(status=EvaluationStatus.FINALIZED)
            .select_related("subject_user__department")
        )
        snaps = kq.attach_effective_snapshots(evals)
        by_dept = {}
        for ev in evals:
            snap = snaps[ev.pk]
            if not snap:
                continue
            name = getattr(ev.subject_user.department, "name", None) or "—"
            row = by_dept.setdefault(name, {"n": 0, "total": 0})
            row["n"] += 1
            row["total"] += snap.final_score
        rows = [
            {"dept": k, "n": v["n"], "avg": (v["total"] / v["n"]).quantize(Decimal("0.01"))}
            for k, v in sorted(by_dept.items())
        ]
        return {"kind": "scoped", "rows": rows}
    own = kq.my_finalized_evaluations(user)
    if own:
        total = sum(s.final_score for _e, s in own)
        return {"kind": "own", "n": len(own), "avg": (total / len(own)).quantize(Decimal("0.01"))}
    return {"kind": "own", "n": 0, "avg": None}


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
            "periodic": periodic_stats(qs),
            "kpi": kpi_stats(user),
            "charts": report_charts(qs, now, year),
        },
    )
