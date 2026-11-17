"""WP3: KpiCapabilityGrant + policy gates (PLAN §5.2–§5.3)."""

import pytest
from django.db import IntegrityError
from django.test import override_settings

from apps.kpi import policies
from apps.kpi.capabilities import KpiCapability
from apps.kpi.models import (
    GrantScope,
    KpiCapabilityGrant,
    KpiReminderEvent,
)

pytestmark = pytest.mark.django_db


def _grant(org, user, cap, scope=GrantScope.UNIT, dept=None, unit=None):
    return KpiCapabilityGrant.objects.create(
        unit=unit or user.unit,
        user=user,
        capability=cap,
        scope=scope,
        department=dept,
        granted_by=org.admin,
        reason="test",
    )


def test_grant_unlocks_capability_and_revoke_relocks(org):
    u = org.leader
    assert not policies.has_capability(u, KpiCapability.CONFIG_EDIT)
    g = _grant(org, u, KpiCapability.CONFIG_EDIT)
    assert policies.has_capability(u, KpiCapability.CONFIG_EDIT)
    g.revoked_at = "2026-01-01T00:00:00Z"
    g.save()
    assert not policies.has_capability(u, KpiCapability.CONFIG_EDIT)


def test_sys_admin_denied_business_capability_even_granted_and_superuser(org):
    u = org.admin
    u.is_superuser = True
    u.save()
    _grant(org, u, KpiCapability.VIEW_UNIT)
    _grant(org, u, KpiCapability.EVALUATE)
    for cap in (KpiCapability.VIEW_UNIT, KpiCapability.EVALUATE, KpiCapability.CONFIG_VIEW):
        assert not policies.has_capability(u, cap)
    # ...but may hold GRANT_MANAGE for the admin grant flow
    _grant(org, u, KpiCapability.GRANT_MANAGE)
    assert policies.can_manage_grants(u)


def test_flag_off_denies_everything(org):
    _grant(org, org.leader, KpiCapability.VIEW_UNIT)
    with override_settings(KPI_ENABLED=False):
        assert not policies.has_capability(org.leader, KpiCapability.VIEW_UNIT)
        assert not policies.can_view_personal_score(org.o1)


def test_cross_unit_grant_ineffective(org):
    _grant(org, org.leader, KpiCapability.CONFIG_EDIT, unit=org.ub)
    assert not policies.has_capability(org.leader, KpiCapability.CONFIG_EDIT)


def test_view_unit_requires_leader_role(org):
    _grant(org, org.mgr1, KpiCapability.VIEW_UNIT)
    assert not policies.has_capability(org.mgr1, KpiCapability.VIEW_UNIT)
    _grant(org, org.leader, KpiCapability.VIEW_UNIT)
    assert policies.has_capability(org.leader, KpiCapability.VIEW_UNIT)


def test_department_scope(org):
    g = _grant(org, org.mgr1, KpiCapability.EVALUATE, scope=GrantScope.DEPARTMENT, dept=org.d1)
    assert policies.has_capability(org.mgr1, KpiCapability.EVALUATE, department_id=org.d1.pk)
    assert not policies.has_capability(org.mgr1, KpiCapability.EVALUATE, department_id=org.d2.pk)
    # DEPARTMENT grant does not open unit-wide operations
    assert not policies.has_capability(org.mgr1, KpiCapability.EVALUATE)
    g.delete()
    _grant(org, org.mgr1, KpiCapability.EVALUATE, scope=GrantScope.UNIT)
    assert policies.has_capability(org.mgr1, KpiCapability.EVALUATE, department_id=org.d2.pk)


def test_uniq_active_grant(org):
    _grant(org, org.leader, KpiCapability.CONFIG_EDIT)
    with pytest.raises(IntegrityError):
        _grant(org, org.leader, KpiCapability.CONFIG_EDIT)


def test_reminder_event_append_only(org):
    from django.db import connection
    from django.db.utils import Error as DbError

    from .conftest import make_record

    rec = make_record(org.leader, org.d1, [org.o1], ref="KPI-REM")
    ev = KpiReminderEvent.objects.create(
        unit=org.ua, record=rec, subject_user=org.o1,
        actor=org.leader, reason="Nhắc hạn", idempotency_key="k1",
    )
    # app layer
    ev.reason = "sửa"
    with pytest.raises(PermissionError):
        ev.save()
    with pytest.raises(PermissionError):
        KpiReminderEvent.objects.filter(pk=ev.pk).update(reason="x")
    # DB trigger
    with pytest.raises(DbError), connection.cursor() as cur:
        cur.execute("UPDATE kpi_kpireminderevent SET reason='x' WHERE id=%s", [str(ev.pk)])


def test_reminder_idempotency_key_unique_per_unit(org):
    from .conftest import make_record

    rec = make_record(org.leader, org.d1, [org.o1], ref="KPI-REM2")
    args = dict(record=rec, subject_user=org.o1, actor=org.leader, reason="r", idempotency_key="dup")
    KpiReminderEvent.objects.create(unit=org.ua, **args)
    # same key different unit OK
    KpiReminderEvent.objects.create(unit=org.ub, **args)
    with pytest.raises(IntegrityError):
        KpiReminderEvent.objects.create(unit=org.ua, **args)
