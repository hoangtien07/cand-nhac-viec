"""SPEC FEEDBACK V2 — repro/regression tests (EU-03 task_code, EU-06 năm làm việc).

WP0: viết trước khi sửa — các test này FAIL trên baseline 71272c3.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.records import services
from apps.records.dashboard_queries import assigned_records

from .conftest import today

pytestmark = pytest.mark.django_db


def _plan(org, *, year=None, days=None, **kw):
    year = year if year is not None else today().year
    return services.create_periodic_plan(
        org.leader,
        name=kw.pop("name", "Báo cáo định kỳ"),
        owner_department=org.d1,
        year=year,
        due_dates=days,
        assignees=[org.o1],
        reference_no="VB-DK/TEST",
        **kw,
    )


# --- EU-03: task_code chung cho nhiều kỳ không được gây IntegrityError/500 (AC-03.2, T-08) ---


def test_plan_with_task_code_multi_period_no_500(org):
    days = [datetime.date(today().year, 3, 15), datetime.date(today().year, 6, 15)]
    plan = _plan(org, days=days, task_code="BC-TT")
    codes = list(plan.periods.order_by("period_index").values_list("task_code", flat=True))
    assert len(codes) == 2
    assert all(codes)  # mọi kỳ vẫn có mã (không rỗng)
    assert len(set(codes)) == 2  # nhưng duy nhất theo đơn vị


def test_plan_with_task_code_12_periods(org):
    days = [datetime.date(today().year, m, 15) for m in range(1, 13)]
    plan = _plan(org, days=days, task_code="BC-NAM")
    assert plan.periods.count() == 12
    assert plan.periods.values("task_code").distinct().count() == 12


def test_plan_task_code_collision_is_form_error(org):
    """Trùng mã kỳ với record đã có → ValidationError (400), không IntegrityError."""
    days = [datetime.date(today().year, 3, 15), datetime.date(today().year, 6, 15)]
    _plan(org, days=days, task_code="BC-TT")
    with pytest.raises(ValidationError):
        _plan(org, days=days, task_code="BC-TT")


# --- EU-06: kỳ định kỳ hiển thị theo năm KẾ HOẠCH/hạn, không theo created_at (AC-06.4, T-09) ---


def test_next_year_periods_visible_in_next_year(org):
    """Plan tạo năm N nhưng các kỳ thuộc năm N+1 → xuất hiện khi chọn năm N+1."""
    next_year = today().year + 1
    days = [datetime.date(next_year, m, 15) for m in (2, 5)]
    _plan(org, year=next_year, days=days)
    qs_next = assigned_records(org.o1, next_year)
    assert qs_next.filter(periodic_plan__isnull=False).count() == 2


def test_next_year_periods_not_in_current_year_list(org):
    next_year = today().year + 1
    days = [datetime.date(next_year, 3, 15)]
    _plan(org, year=next_year, days=days)
    qs_cur = assigned_records(org.o1, today().year)
    assert not qs_cur.filter(periodic_plan__isnull=False).exists()


# --- EU-07: drill-down các KỲ quá hạn (AC-07.x, T-16) ---


def test_periodic_overdue_drilldown_lists_only_overdue_periods(org, client_for):
    year = today().year
    plan = _plan(
        org,
        days=[datetime.date(year, 1, 10), datetime.date(year, 12, 10)],
    )
    # ép kỳ 1 quá hạn, kỳ 2 còn hạn xa
    rec1 = plan.periods.order_by("period_index")[0]
    from apps.records.timeutils import db_now as _now

    rec1.due_at = _now() - datetime.timedelta(days=3)
    rec1.save(update_fields=["due_at"])
    res = client_for(org.leader).get("/ho-so/dinh-ky/qua-han/")
    assert res.status_code == 200
    periods = res.context["periods"]
    assert [r.pk for r in periods] == [rec1.pk]
    content = res.content.decode()
    assert "Kỳ 1" in content and "3 ngày" in content


def test_periodic_overdue_plan_filter_and_404(org, client_for):
    year = today().year
    plan = _plan(org, days=[datetime.date(year, 1, 10)])
    rec1 = plan.periods.get()
    from apps.records.timeutils import db_now as _now

    rec1.due_at = _now() - datetime.timedelta(days=1)
    rec1.save(update_fields=["due_at"])
    c = client_for(org.leader)
    res = c.get(f"/ho-so/dinh-ky/qua-han/?plan={plan.pk}")
    assert res.status_code == 200 and [r.pk for r in res.context["periods"]] == [rec1.pk]
    # plan không hợp lệ → 404 (không lộ scope qua UUID đoán được)
    import uuid

    assert c.get(f"/ho-so/dinh-ky/qua-han/?plan={uuid.uuid4()}").status_code == 404
    # plan thuộc unit khác → 404 (không rò scope)
    from apps.organization.models import Department, Unit

    ub = Unit.objects.create(name="Đơn vị Khác")
    d_x = Department.objects.create(unit=ub, name="Phòng X")
    from apps.accounts.models import User

    foreign = User(username="f.leader", full_name="Lãnh đạo X", unit=ub, department=d_x, role="LEADER")
    foreign.set_password("x")
    foreign.save()
    plan_f = services.create_periodic_plan(
        foreign,
        name="Kế hoạch X",
        owner_department=d_x,
        year=year,
        due_dates=[datetime.date(year, 2, 10)],
        assignees=[foreign],
        reference_no="VB-X/001",
    )
    assert c.get(f"/ho-so/dinh-ky/qua-han/?plan={plan_f.pk}").status_code == 403


def test_periodic_detail_chips_filter(org, client_for):
    year = today().year
    plan = _plan(org, days=[datetime.date(year, 1, 10), datetime.date(year, 12, 10)])
    rec1 = plan.periods.get(period_index=1)
    from apps.records.timeutils import db_now as _now

    rec1.due_at = _now() - datetime.timedelta(days=2)
    rec1.save(update_fields=["due_at"])
    c = client_for(org.leader)
    assert len(c.get(f"/ho-so/dinh-ky/{plan.pk}/").context["periods"]) == 2
    assert len(c.get(f"/ho-so/dinh-ky/{plan.pk}/?ky=overdue").context["periods"]) == 1
    assert len(c.get(f"/ho-so/dinh-ky/{plan.pk}/?ky=done").context["periods"]) == 0


# --- EU-06: nhãn nhắc việc kỳ định kỳ gồm tên + kỳ + hạn (AC-06.3) ---


def test_periodic_record_display_name(org):
    plan = _plan(org, days=[datetime.date(today().year, 3, 15)])
    rec = plan.periods.get()
    assert rec.display_name == "Báo cáo định kỳ · Kỳ 1"


# --- EU-05: báo cáo không còn "Đang xử lý" (AC-05.1, T-18) ---


def test_report_html_has_no_dang_xu_ly(org, client_for):
    from .conftest import make_record

    make_record(org.leader, org.d1, [org.o1], ref="RP-1", days=30)
    res = client_for(org.leader).get("/bao-cao/")
    assert res.status_code == 200
    assert "Đang xử lý" not in res.content.decode()


# --- EU-04: thang 15 điểm — biên trừ theo đề xuất (T-12, T-13) ---


def _version_15(org):
    from decimal import Decimal

    from apps.kpi import services as ksvc
    from apps.kpi.capabilities import KpiCapability
    from apps.kpi.management.commands.seed_kpi_draft_15 import BANDS
    from apps.kpi.models import GrantScope, KpiCapabilityGrant

    KpiCapabilityGrant.objects.create(
        unit=org.ua,
        user=org.leader,
        capability=KpiCapability.CONFIG_EDIT,
        scope=GrantScope.UNIT,
        granted_by=org.admin,
        reason="t",
    )
    v = ksvc.create_draft(
        org.leader,
        task_kind="DOCUMENT",
        name="Thang 15 điểm – đề xuất",
        max_points=Decimal("15.00"),
        combination_strategy="MULTIPLICATIVE",
    )
    ksvc.replace_criteria(
        org.leader,
        v.pk,
        [
            {
                "code": "TIENDO",
                "title": "Tiến độ",
                "weight_percent": Decimal("60"),
                "position": 0,
                "description_short": "",
                "required": False,
            },
            {
                "code": "CHATLUONG",
                "title": "Chất lượng",
                "weight_percent": Decimal("40"),
                "position": 1,
                "description_short": "",
                "required": False,
            },
        ],
    )
    ksvc.replace_penalty_bands(org.leader, v.pk, BANDS)
    return v


def test_deduction_boundaries_15_point_scale(org):
    from apps.kpi.models import PenaltyBandKind
    from apps.kpi.scoring import band_deduction

    v = _version_15(org)
    late = {0: 0, 1: 25, 5: 25, 6: 50, 7: 50, 8: 75, 10: 75, 11: 100}
    for days, pct in late.items():
        assert band_deduction(v, PenaltyBandKind.LATE_DAYS, days) == pct
    rem = {0: 0, 1: 25, 2: 50, 3: 75, 4: 100, 5: 100}
    for n, pct in rem.items():
        assert band_deduction(v, PenaltyBandKind.REMINDER_COUNT, n) == pct


def test_expected_scores_at_full_achievement_15(org):
    """100% mọi tiêu chí → điểm kỳ vọng 15.00/11.25/7.50/3.75/0.00."""
    from decimal import Decimal

    from apps.kpi.scoring import compute_score

    v = _version_15(org)
    full = {str(c.pk): Decimal("100") for c in v.criteria.all()}
    expected = {0: "15.00", 3: "11.25", 6: "7.50", 9: "3.75", 12: "0.00"}
    for late_days, score in expected.items():
        got = compute_score(v, full, late_days, 0)["final_score"]
        assert got == Decimal(score)


def test_seed_kpi_draft_15_idempotent_after_family_rename(org):
    """Review PR #8: draft khác đổi family.name thì chạy lại seed vẫn bỏ qua,
    không tạo trùng đề xuất 15đ."""
    from decimal import Decimal

    from django.core.management import call_command

    from apps.kpi import services as ksvc
    from apps.kpi.capabilities import KpiCapability
    from apps.kpi.models import GrantScope, KpiCapabilityGrant, KpiPolicyFamily, PolicyVersionStatus

    KpiCapabilityGrant.objects.create(
        unit=org.ua,
        user=org.leader,
        capability=KpiCapability.CONFIG_EDIT,
        scope=GrantScope.UNIT,
        granted_by=org.admin,
        reason="t",
    )
    # family phải tồn tại (command yêu cầu); tạo sẵn bằng một draft bất kỳ.
    ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="Gốc", max_points=Decimal("10.00"),
        combination_strategy="MULTIPLICATIVE",
    )
    call_command("seed_kpi_draft_15", actor=org.leader.username)
    family = KpiPolicyFamily.objects.get(unit=org.ua, task_kind="DOCUMENT")
    # Người dùng soạn draft khác → family.name bị đổi (create_draft ghi đè tên).
    ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="Tên khác", max_points=Decimal("8.00"),
        combination_strategy="MULTIPLICATIVE",
    )
    call_command("seed_kpi_draft_15", actor=org.leader.username)  # phải bỏ qua
    drafts = family.versions.filter(status=PolicyVersionStatus.DRAFT, max_points=Decimal("15.00"))
    assert drafts.count() == 1


def test_seed_kpi_draft_15_not_confused_by_manual_15_draft(org):
    """Draft 15đ do actor tự soạn (dải trừ khác) không bị nhận nhầm là đề xuất —
    seed vẫn tạo bản đề xuất với đúng BANDS."""
    from decimal import Decimal

    from django.core.management import call_command

    from apps.kpi import services as ksvc
    from apps.kpi.capabilities import KpiCapability
    from apps.kpi.management.commands.seed_kpi_draft_15 import BANDS
    from apps.kpi.models import (
        GrantScope,
        KpiCapabilityGrant,
        KpiPolicyFamily,
        PolicyVersionStatus,
    )

    KpiCapabilityGrant.objects.create(
        unit=org.ua,
        user=org.leader,
        capability=KpiCapability.CONFIG_EDIT,
        scope=GrantScope.UNIT,
        granted_by=org.admin,
        reason="t",
    )
    manual = ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="Draft tay 15đ", max_points=Decimal("15.00"),
        combination_strategy="MULTIPLICATIVE",
    )
    ksvc.replace_penalty_bands(
        org.leader,
        manual.pk,
        [
            {
                "kind": "LATE_DAYS",
                "min_value": 0,
                "max_value": None,
                "deduction_percent": Decimal("10"),
            }
        ],
    )
    call_command("seed_kpi_draft_15", actor=org.leader.username)
    family = KpiPolicyFamily.objects.get(unit=org.ua, task_kind="DOCUMENT")
    drafts = family.versions.filter(status=PolicyVersionStatus.DRAFT, max_points=Decimal("15.00"))
    assert drafts.count() == 2
    proposal = drafts.exclude(pk=manual.pk).get()
    assert proposal.penalty_bands.count() == len(BANDS)


# --- EU-02: migration đổi tên 5 tổ idempotent (AC-02.1, T-06) ---


def test_department_rename_migration_idempotent(org):
    import importlib

    from django.apps import apps

    from apps.organization.models import Department, Unit

    mig = importlib.import_module("apps.organization.migrations.0003_rename_demo_departments")
    RENAME, UNIT_NAME, forwards = mig.RENAME, mig.UNIT_NAME, mig.forwards
    ua = Unit.objects.create(name=UNIT_NAME)
    for old in RENAME:
        Department.objects.create(unit=ua, name=old)
    forwards(apps, None)
    names = set(Department.objects.filter(unit=ua).values_list("name", flat=True))
    assert names == set(RENAME.values())
    forwards(apps, None)  # chạy lại không lỗi, không đổi gì
    assert set(Department.objects.filter(unit=ua).values_list("name", flat=True)) == names


def test_normalize_demo_accounts_command(org):
    """Khóa leader.config/approve + cấp grant cho lanhdao.a1/a2; idempotent."""
    from django.core.management import call_command

    from apps.accounts.models import User
    from apps.kpi.models import KpiCapabilityGrant
    from apps.organization.models import Unit

    ua = Unit.objects.create(name="Công an phường A (giả lập)")

    def _mk(name, role):
        u = User(username=name, full_name=name, unit=ua, role=role)
        u.set_password("x")
        u.save()
        return u

    admin = _mk("admin.a", "SYS_ADMIN")
    legacy = _mk("leader.config", "LEADER")
    _mk("leader.approve", "LEADER")
    _mk("lanhdao.a1", "LEADER")
    _mk("lanhdao.a2", "LEADER")
    KpiCapabilityGrant.objects.create(
        unit=ua,
        user=legacy,
        capability="KPI_CONFIG_EDIT",
        scope="UNIT",
        granted_by=admin,
        reason="cũ",
    )
    call_command("normalize_demo_accounts", deactivate=True)
    legacy.refresh_from_db()
    assert legacy.is_active is False
    assert not KpiCapabilityGrant.objects.filter(user=legacy, revoked_at__isnull=True).exists()
    caps_a1 = set(
        KpiCapabilityGrant.objects.filter(user__username="lanhdao.a1", revoked_at__isnull=True).values_list(
            "capability", flat=True
        )
    )
    assert {"KPI_CONFIG_EDIT", "KPI_REMINDER_ISSUE", "KPI_EVALUATE"} <= caps_a1
    call_command("normalize_demo_accounts")  # idempotent
    assert KpiCapabilityGrant.objects.filter(revoked_at__isnull=True).count() == 3 + 3
