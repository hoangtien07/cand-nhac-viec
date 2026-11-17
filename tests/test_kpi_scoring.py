"""WP5: reminders, evaluation, score engine, finalize, corrections (PLAN §9 test matrix)."""

import threading
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections

from apps.kpi import evaluation_services as esvc
from apps.kpi import reminder_services as rsvc
from apps.kpi import services as ksvc
from apps.kpi.models import (
    EvaluationStatus,
    KpiEvaluation,
    KpiPolicyVersion,
    KpiScoreSnapshot,
)
from apps.kpi.scoring import compute_score
from apps.records import services as rsc

from .conftest import make_record
from .test_kpi_config import BANDS, CRIT
from .test_kpi_permissions import _grant

pytestmark = pytest.mark.django_db


@pytest.fixture
def ready(org):
    """ACTIVE policy + evaluator/finalizer grants on leader, mgr1 has DEPARTMENT eval grant."""
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    _grant(org, org.leader, "KPI_EVALUATE")
    _grant(org, org.leader, "KPI_SCORE_FINALIZE")
    _grant(org, org.leader, "KPI_SCORE_CORRECT")
    _grant(org, org.leader, "KPI_REMINDER_ISSUE")
    _grant(org, org.mgr1, "KPI_EVALUATE", scope="DEPARTMENT", dept=org.d1)
    _grant(org, org.mgr1, "KPI_REMINDER_ISSUE", scope="DEPARTMENT", dept=org.d1)
    v = ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="Thang KPI",
        max_points=Decimal("100"), combination_strategy="MAX_DEDUCTION",
    )
    ksvc.replace_criteria(org.leader, v.pk, CRIT)
    ksvc.replace_penalty_bands(org.leader, v.pk, BANDS)
    ksvc.publish_version(org.leader, v.pk, "kích hoạt test")
    v.refresh_from_db()
    return v


def _done_record(org, days=2, ref="KPI-EV"):
    rec = make_record(org.leader, org.d1, [org.o1], ref=ref, days=days)
    rsc.submit_result_reference(org.o1, rec.pk, f"KQ-{ref}"[:200])
    rec.refresh_from_db()
    return rec


def test_reminder_issue_idempotent_and_scope(ready, org):
    rec = _done_record(org)
    ev1 = rsvc.issue_reminder(
        org.mgr1, record_id=rec.pk, subject_user_id=org.o1.pk,
        reason="Trễ", idempotency_key="rem-1",
    )
    ev2 = rsvc.issue_reminder(
        org.mgr1, record_id=rec.pk, subject_user_id=org.o1.pk,
        reason="Trễ", idempotency_key="rem-1",
    )
    assert ev1.pk == ev2.pk
    # mgr2 has no grant for d1
    with pytest.raises(PermissionDenied):
        rsvc.issue_reminder(
            org.mgr2, record_id=rec.pk, subject_user_id=org.o1.pk,
            reason="x", idempotency_key="rem-2",
        )
    # non-assignee subject rejected
    with pytest.raises(ValidationError):
        rsvc.issue_reminder(
            org.mgr1, record_id=rec.pk, subject_user_id=org.o2.pk,
            reason="x", idempotency_key="rem-3",
        )


def test_reminder_revoke_lowers_count(ready, org):
    rec = _done_record(org)
    ev = rsvc.issue_reminder(
        org.mgr1, record_id=rec.pk, subject_user_id=org.o1.pk,
        reason="r", idempotency_key="rv-1",
    )
    assert rsvc.valid_reminder_count(rec, org.o1.pk) == 1
    rsvc.revoke_reminder(org.leader, event_id=ev.pk, reason="hủy")
    assert rsvc.valid_reminder_count(rec, org.o1.pk) == 0
    # double revoke idempotent
    rsvc.revoke_reminder(org.leader, event_id=ev.pk, reason="lại")
    from apps.kpi.models import KpiReminderRevocation

    assert KpiReminderRevocation.objects.count() == 1


def test_evaluation_flow_finalize(ready, org):
    rec = make_record(org.leader, org.d1, [org.o1], ref="KPI-EV")  # OPEN
    # evaluate: leader with UNIT grant
    ev, created = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    assert created and ev.policy_version.status == "ACTIVE"
    marks = {str(c.pk): 100 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks, expected_row_version=ev.row_version)
    ev.refresh_from_db()
    # record OPEN → cannot finalize (WP5 gate)
    with pytest.raises(ValidationError):
        esvc.finalize_evaluation(org.leader, ev.pk)
    rsc.submit_result_reference(org.o1, rec.pk, "KQ-EV")
    snap = esvc.finalize_evaluation(org.leader, ev.pk)
    ev.refresh_from_db()
    assert ev.status == "FINALIZED" and ev.finalized_by == org.leader
    assert snap.revision == 1 and snap.final_score >= 0
    # double finalize returns same snapshot
    snap2 = esvc.finalize_evaluation(org.leader, ev.pk)
    assert snap2.pk == snap.pk and KpiScoreSnapshot.objects.count() == 1
    # no marks change after finalize
    with pytest.raises(ValidationError):
        esvc.save_marks(org.leader, ev.pk, marks)


def test_finalize_requires_all_marks(ready, org):
    rec = _done_record(org)
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    one = {str(ev.policy_version.criteria.first().pk): 80}
    esvc.save_marks(org.leader, ev.pk, one, expected_row_version=ev.row_version)
    with pytest.raises(ValidationError):
        esvc.finalize_evaluation(org.leader, ev.pk)


def test_correction_creates_new_revision(ready, org):
    rec = _done_record(org)
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    marks = {str(c.pk): 100 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks, expected_row_version=ev.row_version)
    snap1 = esvc.finalize_evaluation(org.leader, ev.pk)
    new_marks = {k: Decimal("50") for k in marks}
    snap2 = esvc.correct_score(org.leader, ev.pk, reason="Sai điểm tiêu chí", marks=new_marks)
    assert snap2.revision == 2 and snap2.final_score != snap1.final_score
    assert esvc.effective_snapshot(ev).pk == snap2.pk
    assert KpiScoreSnapshot.objects.filter(evaluation=ev).count() == 2
    snap1.refresh_from_db()  # untouched (append-only)
    assert snap1.revision == 1


def test_row_version_conflict(ready, org):
    rec = _done_record(org)
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    marks = {str(c.pk): 80 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks, expected_row_version=ev.row_version)
    with pytest.raises(ValidationError):
        esvc.save_marks(org.leader, ev.pk, marks, expected_row_version=ev.row_version)  # stale


def test_sec_manager_scope_dept(ready, org):
    """KPI-SEC-07: DEPARTMENT grant chấm người tổ khác → denied."""
    rec_d2 = make_record(org.leader, org.d2, [org.o2], ref="KPI-D2")
    rsc.submit_result_reference(org.o2, rec_d2.pk, "KQ")
    with pytest.raises(PermissionDenied):
        esvc.get_or_create_evaluation(
            org.mgr1, record_id=rec_d2.pk, subject_user_id=org.o2.pk
        )
    with pytest.raises(PermissionDenied):
        rsvc.issue_reminder(
            org.mgr1, record_id=rec_d2.pk, subject_user_id=org.o2.pk,
            reason="x", idempotency_key="sec7",
        )


def test_sec_revoked_grant_blocks_post(ready, org):
    """KPI-SEC-08: thu hồi grant trước POST chốt → bị chặn."""
    rec = _done_record(org)
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    marks = {str(c.pk): 100 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks)
    from apps.kpi.models import KpiCapabilityGrant

    g = KpiCapabilityGrant.objects.get(user=org.leader, capability="KPI_SCORE_FINALIZE")
    g.revoked_at = "2026-01-01T00:00:00Z"
    g.save()
    with pytest.raises(PermissionDenied):
        esvc.finalize_evaluation(org.leader, ev.pk)


def test_sec_404_cross_unit_and_offender_isolation(ready, org, client_for):
    """KPI-SEC-01/04: điểm người khác/đơn vị khác → 404/403."""
    rec = _done_record(org)
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    marks = {str(c.pk): 100 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks)
    esvc.finalize_evaluation(org.leader, ev.pk)
    # officer khác tổ → 403
    r = client_for(org.o2).get(f"/kpi/danh-gia/{ev.pk}/")
    assert r.status_code == 403
    # cross-unit leader → 404
    r = client_for(org.bleader).get(f"/kpi/danh-gia/{ev.pk}/")
    assert r.status_code == 404
    # chính subject xem được điểm đã chốt
    r = client_for(org.o1).get(f"/kpi/danh-gia/{ev.pk}/")
    assert r.status_code == 200


def test_sec_sysadmin_403(ready, org, client_for):
    """KPI-SEC-05: SYS_ADMIN is_superuser → 403 trên trang KPI."""
    org.admin.is_superuser = True
    org.admin.save()
    rec = _done_record(org)
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    r = client_for(org.admin).get(f"/kpi/danh-gia/{ev.pk}/")
    assert r.status_code in (403, 404)


# --- calculation matrix (KPI-CALC) ---


def test_calc_matrix(ready):
    v = KpiPolicyVersion.objects.get(pk=ready.pk)
    ach = {str(c.pk): 100 for c in v.criteria.all()}
    # KPI-CALC-01..08 (band LATE_DAYS: 0-5→0, 6-7→25, 8-10→50, 11+→100)
    for days, exp in [(0, 0), (1, 0), (5, 0), (6, 25), (7, 25), (8, 50), (10, 50), (11, 100)]:
        r = compute_score(v, ach, days, 0)
        assert r["late_deduction_percent"] == Decimal(exp), days
        assert Decimal("0") <= r["final_score"] <= v.max_points
    # KPI-CALC-09 reminder 1..5 → 0,0,25,25,25 (bands 0-2→0, 3+→25)
    for n, exp in [(1, 0), (2, 0), (3, 25), (4, 25), (5, 25)]:
        r = compute_score(v, ach, 0, n)
        assert r["reminder_deduction_percent"] == Decimal(exp), n


def test_calc_weighted_base(ready):
    """KPI-CALC-13: weights 60/40, marks 50/80 → base = 100*(.6*.5 + .4*.8) = 62."""
    v = KpiPolicyVersion.objects.get(pk=ready.pk)
    cs = list(v.criteria.all())
    ach = {str(cs[0].pk): 50, str(cs[1].pk): 80}
    r = compute_score(v, ach, 0, 0)
    assert r["base_score"] == Decimal("62.00")


@pytest.mark.django_db(transaction=True)
def test_concurrent_finalize_single_snapshot(org_tx):
    """KPI-CALC-19: 2 POST chốt song song → 1 snapshot."""
    org = org_tx
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    _grant(org, org.leader, "KPI_EVALUATE")
    _grant(org, org.leader, "KPI_SCORE_FINALIZE")
    v = ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="T",
        max_points=Decimal("100"), combination_strategy="MAX_DEDUCTION",
    )
    ksvc.replace_criteria(org.leader, v.pk, CRIT)
    ksvc.replace_penalty_bands(org.leader, v.pk, BANDS)
    ksvc.publish_version(org.leader, v.pk, "ok")
    rec = make_record(org.leader, org.d1, [org.o1], ref="RACE")
    rsc.submit_result_reference(org.o1, rec.pk, "KQ")
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=org.o1.pk
    )
    marks = {str(c.pk): 100 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks)

    results, errors = [], []
    barrier = threading.Barrier(2)

    def run():
        try:
            barrier.wait(timeout=10)
            results.append(esvc.finalize_evaluation(org.leader, ev.pk))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connections.close_all()

    t1, t2 = threading.Thread(target=run), threading.Thread(target=run)
    t1.start()
    t2.start()
    t1.join(30)
    t2.join(30)
    assert len(results) == 2 and results[0].pk == results[1].pk
    assert KpiScoreSnapshot.objects.filter(evaluation=ev).count() == 1
    ev_db = KpiEvaluation.objects.get(pk=ev.pk)
    assert ev_db.status == EvaluationStatus.FINALIZED
    assert not errors


@pytest.mark.django_db(transaction=True)
def test_concurrent_publish_single_active(org_tx):
    """KPI-CALC-18: 2 publish song song → đúng 1 ACTIVE."""
    org = org_tx
    _grant(org, org.leader, "KPI_CONFIG_EDIT")
    _grant(org, org.leader, "KPI_CONFIG_PUBLISH")
    v1 = ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="T",
        max_points=Decimal("100"), combination_strategy="MAX_DEDUCTION",
    )
    v2 = ksvc.create_draft(
        org.leader, task_kind="DOCUMENT", name="T",
        max_points=Decimal("100"), combination_strategy="MAX_DEDUCTION",
    )
    for v in (v1, v2):
        ksvc.replace_criteria(org.leader, v.pk, CRIT)
        ksvc.replace_penalty_bands(org.leader, v.pk, BANDS)
    errors = []
    barrier = threading.Barrier(2)

    def pub(vid):
        try:
            barrier.wait(timeout=10)
            ksvc.publish_version(org.leader, vid, "race")
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=pub, args=(v1.pk,))
    t2 = threading.Thread(target=pub, args=(v2.pk,))
    t1.start()
    t2.start()
    t1.join(30)
    t2.join(30)
    statuses = sorted(
        KpiPolicyVersion.objects.filter(family__unit=org.ua).values_list("status", flat=True)
    )
    assert statuses == ["ACTIVE", "SUPERSEDED"] and not errors


# --- WP6 UI ---


def _finalized(org, ready, subject=None):
    subject = subject or org.o1
    rec = make_record(org.leader, org.d1, [subject], ref="UI-1", days=2)
    rsc.submit_result_reference(subject, rec.pk, "KQ-UI")
    ev, _ = esvc.get_or_create_evaluation(
        org.leader, record_id=rec.pk, subject_user_id=subject.pk
    )
    marks = {str(c.pk): 100 for c in ev.policy_version.criteria.all()}
    esvc.save_marks(org.leader, ev.pk, marks)
    esvc.finalize_evaluation(org.leader, ev.pk)
    return rec, ev


def test_ui_pages_access(ready, org, client_for):
    c_leader, c_o2 = client_for(org.leader), client_for(org.o2)
    for url in ("/kpi/ca-nhan/", "/kpi/bang-diem/", "/kpi/danh-gia/", "/kpi/nhac-nho/"):
        assert c_leader.get(url).status_code == 200, url
    assert c_o2.get("/kpi/ca-nhan/").status_code == 200
    for url in ("/kpi/bang-diem/", "/kpi/danh-gia/", "/kpi/nhac-nho/"):
        assert c_o2.get(url).status_code == 403, url


def test_my_scores_only_own(ready, org, client_for):
    _finalized(org, ready, org.o1)
    _finalized(org, ready, org.o1b)
    r = client_for(org.o1).get("/kpi/ca-nhan/")
    assert r.status_code == 200
    assert len(r.context["rows"]) == 1 and r.context["rows"][0][0].subject_user == org.o1


def test_score_board_scope(ready, org, client_for):
    rec, ev = _finalized(org, ready)
    _grant(org, org.mgr1, "KPI_VIEW_UNIT", scope="DEPARTMENT", dept=org.d1)
    r = client_for(org.mgr1).get("/kpi/bang-diem/")
    assert r.status_code == 200 and any(e.pk == ev.pk for e, _s in r.context["rows"])
    r2 = client_for(org.mgr2).get("/kpi/bang-diem/")
    assert r2.status_code == 403


def test_record_list_kpi_cols(ready, org, client_for):
    rec, ev = _finalized(org, ready)
    r = client_for(org.o1).get("/ho-so/")
    assert r.status_code == 200
    rows = {x.pk: x for x in r.context["page"].object_list}
    assert rows[rec.pk].kpi_eval_label == "Đã chốt"
    assert rows[rec.pk].kpi_own_score is not None
    # cross-subject score not leaked to another officer
    r2 = client_for(org.o2).get("/ho-so/")
    assert r2.status_code == 200


def test_record_detail_own_score_only(ready, org, client_for):
    rec, ev = _finalized(org, ready)
    r = client_for(org.o1).get(f"/ho-so/{rec.pk}/")
    assert r.status_code == 200 and r.context["kpi_own_eval"].pk == ev.pk
    assert "kpi_rows" not in r.context or not r.context.get("kpi_rows")
