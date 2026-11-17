"""WP4: KPI config DRAFT CRUD, validation, preview, publish (PLAN §5.1, WP4 exit)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.kpi import services
from apps.kpi.models import (
    KpiCapabilityGrant,
    KpiPolicyFamily,
    KpiPolicyVersion,
)
from apps.kpi.scoring import band_deduction, compute_score

from .test_kpi_permissions import _grant

pytestmark = pytest.mark.django_db

CRIT = [
    {"code": "TIENDO", "title": "Tiến độ", "weight_percent": Decimal("60"), "position": 0,
     "description_short": "", "required": False},
    {"code": "CHATLUONG", "title": "Chất lượng", "weight_percent": Decimal("40"), "position": 1,
     "description_short": "", "required": False},
]
BANDS = [
    {"kind": "LATE_DAYS", "min_value": 0, "max_value": 5, "deduction_percent": Decimal("0")},
    {"kind": "LATE_DAYS", "min_value": 6, "max_value": 7, "deduction_percent": Decimal("25")},
    {"kind": "LATE_DAYS", "min_value": 8, "max_value": 10, "deduction_percent": Decimal("50")},
    {"kind": "LATE_DAYS", "min_value": 11, "max_value": None, "deduction_percent": Decimal("100")},
    {"kind": "REMINDER_COUNT", "min_value": 0, "max_value": 2, "deduction_percent": Decimal("0")},
    {"kind": "REMINDER_COUNT", "min_value": 3, "max_value": None, "deduction_percent": Decimal("25")},
]


def _mk_draft(org, strategy="MAX_DEDUCTION", max_points="100", task_kind="DOCUMENT", name="Thang KPI"):
    return services.create_draft(
        org.leader, task_kind=task_kind, name=name,
        max_points=Decimal(max_points), combination_strategy=strategy,
    )


def _mk_ready(org, **kw):
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    version = _mk_draft(org, **kw)
    services.replace_criteria(org.leader, version.pk, CRIT)
    services.replace_penalty_bands(org.leader, version.pk, BANDS)
    return KpiPolicyVersion.objects.get(pk=version.pk)


def test_draft_requires_edit_grant(org):
    with pytest.raises(PermissionDenied):
        _mk_draft(org)


def test_family_one_per_unit_kind(org):
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    v1 = _mk_draft(org)
    v2 = _mk_draft(org)
    assert v1.family_id == v2.family_id and v2.version == 2
    assert KpiPolicyFamily.objects.count() == 1


def test_validation_catches_bad_config(org):
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    v = _mk_draft(org)
    services.replace_criteria(org.leader, v.pk, CRIT[:1])  # sum=60
    services.replace_penalty_bands(org.leader, v.pk, BANDS[:3])  # missing LATE 11+, no REMINDER
    errors = services.validate_version(KpiPolicyVersion.objects.get(pk=v.pk))
    assert any("100" in e for e in errors)
    assert any("nhắc" in e.lower() or "REMINDER" in e for e in errors)


def test_validation_band_gap_and_overlap(org):
    gapped = [
        {"kind": "LATE_DAYS", "min_value": 0, "max_value": 5, "deduction_percent": Decimal("0")},
        {"kind": "LATE_DAYS", "min_value": 7, "max_value": None, "deduction_percent": Decimal("10")},
    ]
    assert services._band_errors("LATE_DAYS", _bands_objs(gapped))
    overlap = [
        {"kind": "LATE_DAYS", "min_value": 0, "max_value": 6, "deduction_percent": Decimal("0")},
        {"kind": "LATE_DAYS", "min_value": 6, "max_value": None, "deduction_percent": Decimal("10")},
    ]
    assert services._band_errors("LATE_DAYS", _bands_objs(overlap))
    open_mid = [
        {"kind": "LATE_DAYS", "min_value": 0, "max_value": None, "deduction_percent": Decimal("0")},
        {"kind": "LATE_DAYS", "min_value": 10, "max_value": None, "deduction_percent": Decimal("5")},
    ]
    assert services._band_errors("LATE_DAYS", _bands_objs(open_mid))
    assert not services._band_errors("LATE_DAYS", _bands_objs([
        {"kind": "LATE_DAYS", "min_value": 0, "max_value": 5, "deduction_percent": Decimal("0")},
        {"kind": "LATE_DAYS", "min_value": 6, "max_value": None, "deduction_percent": Decimal("10")},
    ]))


def _bands_objs(rows):
    from apps.kpi.models import KpiPenaltyBand

    return [KpiPenaltyBand(**r) for r in rows]


def test_publish_requires_publish_grant_and_reason(org):
    v = _mk_ready(org)
    with pytest.raises(PermissionDenied):
        services.publish_version(org.leader, v.pk, "ok")  # no PUBLISH grant
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    with pytest.raises(ValidationError):
        services.publish_version(org.leader, v.pk, "   ")  # empty reason
    services.publish_version(org.leader, v.pk, "Quyết định 01/2026")
    v.refresh_from_db()
    assert v.status == "ACTIVE" and v.fingerprint and v.published_by == org.leader
    assert v.family.active_version_id == v.pk
    assert AuditEvent.objects.filter(action="kpi.config_published").exists()


def test_publish_supersedes_previous_active(org):
    v1 = _mk_ready(org)
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    services.publish_version(org.leader, v1.pk, "lần 1")
    v2 = _mk_draft(org)
    services.replace_criteria(org.leader, v2.pk, CRIT)
    services.replace_penalty_bands(org.leader, v2.pk, BANDS)
    services.publish_version(org.leader, v2.pk, "lần 2")
    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v1.status == "SUPERSEDED" and v2.status == "ACTIVE"


def test_active_version_immutable(org):
    v = _mk_ready(org)
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    services.publish_version(org.leader, v.pk, "ok")
    with pytest.raises(ValidationError):
        services.update_draft(org.leader, v.pk, max_points=Decimal("200"),
                              combination_strategy="MAX_DEDUCTION")
    with pytest.raises(ValidationError):
        services.replace_criteria(org.leader, v.pk, CRIT)


def test_publish_rejected_when_config_invalid(org):
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    v = _mk_draft(org)  # no criteria/bands
    with pytest.raises(ValidationError):
        services.publish_version(org.leader, v.pk, "ok")


def test_score_engine_strategies(org):
    v = _mk_ready(org)
    ach = {str(c.pk): 100 for c in v.criteria.all()}
    base = compute_score(v, ach, 0, 0)["base_score"]
    assert base == Decimal("100.00")
    # B=100, L=50 (trễ 9 ngày), R=25 (3 nhắc) — ví dụ KPI-CALC-11/12 trong plan
    assert compute_score(v, ach, 9, 3, strategy="MAX_DEDUCTION")["final_score"] == Decimal("50.00")
    assert compute_score(v, ach, 9, 3, strategy="CAPPED_ADDITIVE")["final_score"] == Decimal("25.00")
    assert compute_score(v, ach, 9, 3, strategy="MULTIPLICATIVE")["final_score"] == Decimal("37.50")
    # edge days 0/1/5/6/7/8/10/11
    expected = {0: 0, 1: 0, 5: 0, 6: 25, 7: 25, 8: 50, 10: 50, 11: 100}
    for days, pct in expected.items():
        assert band_deduction(v, "LATE_DAYS", days) == Decimal(str(pct)), days


def test_ui_config_flow(org, client_for):
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    c = client_for(org.leader)
    r = c.get("/kpi/cau-hinh/")
    assert r.status_code == 200
    r = c.post("/kpi/cau-hinh/tao/", {
        "task_kind": "DOCUMENT", "name": "Thang KPI", "max_points": "100",
        "combination_strategy": "MAX_DEDUCTION", "clone_from": "",
    })
    assert r.status_code == 302
    v = KpiPolicyVersion.objects.get()
    # officer without grants can't touch it
    assert client_for(org.o1).get(f"/kpi/cau-hinh/{v.pk}/").status_code == 403
    # cross-unit leader gets 404 (no existence leak)
    KpiCapabilityGrant.objects.create(
        unit=org.ub, user=org.bleader, capability="KPI_CONFIG_VIEW",
        scope="UNIT", granted_by=org.admin,
    )
    assert client_for(org.bleader).get(f"/kpi/cau-hinh/{v.pk}/").status_code == 404


def test_flag_off_returns_404(org, client_for):
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    with override_settings(KPI_ENABLED=False):
        assert client_for(org.leader).get("/kpi/cau-hinh/").status_code == 404


def test_grant_flow_metadata_only(org, client_for):
    _grant(org, org.admin, "KPI_GRANT_MANAGE")
    c = client_for(org.admin)
    r = c.post("/quan-tri/kpi-quyen/", {
        "user": org.mgr1.pk, "capability": "KPI_EVALUATE", "scope": "DEPARTMENT",
        "department": org.d1.pk, "approved_by": org.leader.pk, "reason": "test",
    })
    assert r.status_code == 302
    g = KpiCapabilityGrant.objects.get(user=org.mgr1, capability="KPI_EVALUATE")
    r = c.post(f"/quan-tri/kpi-quyen/{g.pk}/thu-hoi/")
    assert r.status_code == 302
    g.refresh_from_db()
    assert g.revoked_at is not None


def test_cannot_grant_business_cap_to_sysadmin(org):
    _grant(org, org.admin, "KPI_GRANT_MANAGE")
    with pytest.raises(ValidationError):
        services.grant_capability(
            org.admin, user=org.admin, capability="KPI_EVALUATE", scope="UNIT",
        )
