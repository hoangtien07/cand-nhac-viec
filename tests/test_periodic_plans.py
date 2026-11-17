"""WP2: task_kind OTHER/DOCUMENT + PeriodicPlan 1..12 kỳ (STT3/STT10)."""

import datetime

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditEvent
from apps.records import services
from apps.records.models import PeriodicPlan, RecordStatus, TaskKind, WorkRecord

from .conftest import make_record, today

pytestmark = pytest.mark.django_db


def _days(n, start_offset=30):
    base = today() + datetime.timedelta(days=start_offset)
    return [base + datetime.timedelta(days=30 * i) for i in range(n)]


def _make_plan(org, n=4, **kw):
    year = kw.pop("year", today().year)
    days = kw.pop("due_dates", None)
    if days is None:
        days = [d for d in _days(n) if d.year == year]
        if len(days) < n:  # spilled into next year — pad with in-year days
            seen = set(days)
            d = datetime.date(year, 1, 1)
            while len(days) < n:
                d += datetime.timedelta(days=1)
                if d not in seen:
                    days.append(d)
                    seen.add(d)
    return services.create_periodic_plan(
        kw.pop("actor", org.leader),
        name=kw.pop("name", "Báo cáo định kỳ"),
        owner_department=kw.pop("owner_department", org.d1),
        year=year,
        due_dates=days,
        assignees=kw.pop("assignees", [org.o1]),
        reference_no=kw.pop("reference_no", "VB-DK/2026"),
        **kw,
    )


def test_plan_creates_n_records_with_indices(org):
    plan = _make_plan(org, n=4)
    periods = list(plan.periods.order_by("period_index"))
    assert len(periods) == 4 and [p.period_index for p in periods] == [1, 2, 3, 4]
    assert all(p.periodic_plan_id == plan.pk and p.status == "OPEN" for p in periods)
    assert all(p.title == "Báo cáo định kỳ" for p in periods)
    assert AuditEvent.objects.filter(action="periodic_plan.created").exists()


def test_plan_bounds_rejected(org):
    with pytest.raises(ValidationError):
        _make_plan(org, due_dates=[])
    year = today().year
    days13 = [datetime.date(year, 1, d) for d in range(1, 14)]
    with pytest.raises(ValidationError):
        _make_plan(org, due_dates=days13)
    dup = today() + datetime.timedelta(days=10)
    with pytest.raises(ValidationError):
        _make_plan(org, due_dates=[dup, dup])
    other_year = datetime.date(year + 1, 6, 15)
    with pytest.raises(ValidationError):
        _make_plan(org, due_dates=[other_year], year=year)
    assert PeriodicPlan.objects.count() == 0


def test_single_period_plan_ok(org):
    plan = _make_plan(org, n=1)
    assert plan.periods.count() == 1


def test_submit_closes_only_one_period(org):
    plan = _make_plan(org, n=2)
    p1, p2 = plan.periods.order_by("period_index")
    services.submit_result_reference(org.o1, p1.pk, "KQ-1")
    p1.refresh_from_db()
    p2.refresh_from_db()
    assert p1.status == RecordStatus.DONE and p2.status == RecordStatus.OPEN


def test_other_task_confirm_completion(org, client_for):
    rec = services.create_record(
        org.leader,
        task_kind=TaskKind.OTHER,
        title="Kiểm tra địa bàn",
        owner_department=org.d1,
        due_date=today() + datetime.timedelta(days=3),
        assignees=[org.o1],
    )
    assert rec.task_kind == "OTHER" and rec.reference_no == ""
    # non-assignee cannot complete
    with pytest.raises(PermissionDenied):
        services.complete_other_task(org.mgr1, rec.pk)  # sees the record but is no assignee
    services.complete_other_task(org.o1, rec.pk)
    rec.refresh_from_db()
    assert rec.status == "DONE" and rec.completed_by == org.o1
    assert AuditEvent.objects.filter(record=rec, action="record.other_completed").exists()
    # submit_result_reference is rejected for OTHER
    rec2 = services.create_record(
        org.leader,
        task_kind=TaskKind.OTHER,
        title="Nhiệm vụ 2",
        owner_department=org.d1,
        due_date=today() + datetime.timedelta(days=3),
        assignees=[org.o1],
    )
    with pytest.raises(ValidationError):
        services.submit_result_reference(org.o1, rec2.pk, "KQ-X")


def test_other_requires_title(org):
    with pytest.raises(ValidationError):
        services.create_record(
            org.leader,
            task_kind=TaskKind.OTHER,
            title="",
            owner_department=org.d1,
            due_date=today() + datetime.timedelta(days=3),
            assignees=[org.o1],
        )
    assert WorkRecord.objects.count() == 0


def test_document_still_requires_reference(org):
    with pytest.raises(ValidationError):
        services.create_record(
            org.leader,
            task_kind=TaskKind.DOCUMENT,
            owner_department=org.d1,
            due_date=today() + datetime.timedelta(days=3),
            assignees=[org.o1],
        )


def test_periodic_ui(org, client_for):
    plan = _make_plan(org, n=3)
    c = client_for(org.leader)
    res = c.get("/ho-so/dinh-ky/")
    assert res.status_code == 200 and "Báo cáo định kỳ" in res.content.decode()
    res = c.get(f"/ho-so/dinh-ky/{plan.pk}/")
    body = res.content.decode()
    assert res.status_code == 200 and body.count("Kỳ ") >= 3
    # cross-unit officer cannot see the plan
    res_b = client_for(org.b1).get(f"/ho-so/dinh-ky/{plan.pk}/")
    assert res_b.status_code in (403, 404)


def test_periodic_create_via_ui(org, client_for):
    c = client_for(org.leader)
    days = [datetime.date(today().year, m, 20) for m in (3, 6, 9)]
    res = c.post(
        "/ho-so/dinh-ky/tao/",
        {
            "name": "Văn bản quý",
            "task_kind": "DOCUMENT",
            "reference_no": "CV-Q/2026",
            "owner_department": org.d1.pk,
            "year": str(today().year),
            "due_dates": "\n".join(d.isoformat() for d in days),
            "assignees": [str(org.o1.pk)],
        },
    )
    assert res.status_code == 302
    plan = PeriodicPlan.objects.get()
    assert plan.periods.count() == 3


def test_legacy_document_record_unchanged(org):
    rec = make_record(org.leader, org.d1, [org.o1], ref="GL-LEGACY")
    assert rec.task_kind == "DOCUMENT" and rec.periodic_plan_id is None
