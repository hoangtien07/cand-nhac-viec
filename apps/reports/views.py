from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
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
        open=Count("id", filter=Q(status=RecordStatus.OPEN)),
        done=Count("id", filter=Q(status=RecordStatus.DONE)),
        overdue=Count("id", filter=Q(status=RecordStatus.OPEN, due_at__lt=now)),
        due_soon=Count(
            "id", filter=Q(status=RecordStatus.OPEN, due_at__gte=now, due_at__lt=due_soon_cutoff(now))
        ),
        total=Count("id"),
    )
    totals = qs.aggregate(**agg)
    by_dept = qs.values("owner_department__name").annotate(**agg).order_by("owner_department__name")
    return totals, list(by_dept)


@require_GET
def report(request):
    user = request.user
    if not policies.can_view_reports(user):
        raise PermissionDenied("Bạn không có quyền xem báo cáo nghiệp vụ.")
    now = db_now()
    year = get_active_work_year(request)
    totals, by_dept = report_summary(user, now, year=year)
    scope = {
        "LEADER": "Toàn đơn vị",
        "DEPT_MANAGER": "Phòng/đội bạn quản lý và hồ sơ bạn tham gia",
        "OFFICER": "Hồ sơ bạn tạo, giao hoặc được giao",
    }[user.role]
    return render(
        request,
        "reports/report.html",
        {"totals": totals, "by_dept": by_dept, "scope": scope, "now": now, "year": year},
    )
