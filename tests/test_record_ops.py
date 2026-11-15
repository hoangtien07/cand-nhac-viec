"""Record ops pack: direct submit, metadata edit, archive/restore, result corrections."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditEvent
from apps.notifications.models import Notification
from apps.organization import folder_services
from apps.records import services
from apps.records.models import CorrectionKind, RecordStatus, ResultCorrection, WorkRecord

from .conftest import make_record


def _submit(user, rec, code):
    return services.submit_result_reference(user, rec.pk, code)


# ---------- Submit flow (spec §1/§5/§10) ----------


@pytest.mark.django_db
def test_additional_submit_after_done_keeps_completion(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-1")
    _submit(org.o1, rec, "KQ-1")
    rec.refresh_from_db()
    done_at, done_by = rec.completed_at, rec.completed_by
    _submit(org.o1, rec, "KQ-2")
    rec.refresh_from_db()
    assert rec.status == RecordStatus.DONE
    assert rec.completed_at == done_at and rec.completed_by == done_by
    assert rec.results.count() == 2


@pytest.mark.django_db
def test_revoked_assignee_cannot_submit(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-2")
    services.update_assignment(org.leader, rec.pk, [org.o1b])
    # revoke mất luôn quyền xem → deny-by-default trả 404/DoesNotExist
    with pytest.raises(WorkRecord.DoesNotExist):
        _submit(org.o1, rec, "KQ-X")
    res = client_for(org.o1).post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-X"})
    assert res.status_code == 404


@pytest.mark.django_db
def test_share_viewer_and_watcher_cannot_submit(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-3", watchers=[org.o2b])
    folder_services.share_record(org.leader, rec.pk, org.o2.pk)
    for u in (org.o2, org.o2b):
        with pytest.raises(PermissionDenied):
            _submit(u, rec, "KQ-V")


@pytest.mark.django_db
def test_cross_unit_cannot_view_edit_submit_archive(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-4")
    c = client_for(org.bleader)
    assert c.get(f"/ho-so/{rec.pk}/").status_code == 404
    assert c.get(f"/ho-so/{rec.pk}/sua/").status_code == 404
    assert c.post(f"/ho-so/{rec.pk}/nop/", {"code": "X"}).status_code == 404
    assert c.post(f"/ho-so/{rec.pk}/luu-tru/", {"reason": "x"}).status_code == 404


# ---------- Metadata edit (spec §3) ----------


@pytest.mark.django_db
def test_edit_open_record_writes_audit(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-5")
    res = client_for(org.mgr1).post(
        f"/ho-so/{rec.pk}/sua/",
        {
            "reference_no": "OPS-5-S",
            "owner_department": str(rec.owner_department_id),
            "folder": "",
            "due_date": rec.due_at.date().isoformat(),
            "assignees": [str(org.o1.pk)],
            "watchers": [],
        },
        follow=True,
    )
    assert res.status_code == 200
    rec.refresh_from_db()
    assert rec.reference_no == "OPS-5-S"
    assert AuditEvent.objects.filter(
        record=rec, action="record.updated", metadata__field="reference_no"
    ).exists()


@pytest.mark.django_db
def test_edit_done_record_denied(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-6")
    _submit(org.o1, rec, "KQ-D")
    res = client_for(org.mgr1).get(f"/ho-so/{rec.pk}/sua/")
    assert res.status_code == 403


@pytest.mark.django_db
def test_edit_by_unauthorized_user_denied(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-7")
    folder_services.share_record(org.leader, rec.pk, org.o2.pk)
    res = client_for(org.o2).get(f"/ho-so/{rec.pk}/sua/")
    assert res.status_code == 403
    before = rec.reference_no
    client_for(org.o2).post(
        f"/ho-so/{rec.pk}/sua/", {"reference_no": "HACK", "owner_department": str(rec.owner_department_id)}
    )
    rec.refresh_from_db()
    assert rec.reference_no == before


@pytest.mark.django_db
def test_owner_department_change_stays_in_scope(org):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-8")
    with pytest.raises(PermissionDenied):
        services.update_owner_department(org.mgr1, rec.pk, org.d2)  # mgr1 không quản d2
    services.update_owner_department(org.leader, rec.pk, org.d2)
    rec.refresh_from_db()
    assert rec.owner_department_id == org.d2.pk


# ---------- Archive / restore (spec §4) ----------


@pytest.mark.django_db
def test_archive_hides_record_and_stops_reminders(org, client_for):
    from apps.notifications.services import remind_record

    rec = make_record(org.mgr1, org.d1, [org.o1], ref="OPS-9", days=-1)
    n = remind_record(rec.pk)
    assert n >= 0
    services.archive_record(org.mgr1, rec.pk, "Tạo nhầm")
    rec.refresh_from_db()
    assert rec.archived_at is not None and rec.archived_by == org.mgr1
    # excluded from active list, visible via ARCHIVED filter
    body = client_for(org.mgr1).get("/ho-so/").content.decode()
    assert "OPS-9" not in body
    body = client_for(org.mgr1).get("/ho-so/", {"status": "ARCHIVED"}).content.decode()
    assert "OPS-9" in body
    # no new reminders for archived record; pending ones resolved
    assert remind_record(rec.pk) == 0
    assert not Notification.objects.filter(record=rec, resolved_at__isnull=True).exists()


@pytest.mark.django_db
def test_archive_requires_open_without_results(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-10")
    _submit(org.o1, rec, "KQ-A")
    with pytest.raises(PermissionDenied):
        services.archive_record(org.leader, rec.pk, "x")
    # share viewer cannot archive either
    rec2 = make_record(org.leader, org.d1, [org.o1], ref="OPS-11")
    folder_services.share_record(org.leader, rec2.pk, org.o2.pk)
    res = client_for(org.o2).post(f"/ho-so/{rec2.pk}/luu-tru/", {"reason": "x"})
    assert res.status_code == 403
    assert rec2.archived_at is None


@pytest.mark.django_db
def test_restore_returns_record_to_active_lists(org, client_for):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="OPS-12")
    services.archive_record(org.mgr1, rec.pk, "Nhầm")
    services.restore_record(org.mgr1, rec.pk)
    rec.refresh_from_db()
    assert rec.archived_at is None
    assert "OPS-12" in client_for(org.mgr1).get("/ho-so/").content.decode()
    assert AuditEvent.objects.filter(record=rec, action="record.restored").exists()


# ---------- Result corrections (spec §6) ----------


@pytest.mark.django_db
def test_correction_keeps_original_and_replacement(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-13")
    res1 = _submit(org.o1, rec, "KQ-OLD").result
    repl = services.correct_result_reference(org.o1, rec.pk, res1.pk, "KQ-NEW", "Ghi sai số")
    res1.refresh_from_db()
    assert res1.effective_status == "Đã được thay thế"
    assert repl.effective_status == "Có hiệu lực"
    corr = ResultCorrection.objects.get(result=res1)
    assert corr.kind == CorrectionKind.CORRECT and corr.replacement == repl
    assert AuditEvent.objects.filter(record=rec, action="result.corrected").exists()
    # original row untouched (immutable)
    assert res1.code == "KQ-OLD"


@pytest.mark.django_db
def test_revoke_last_effective_result_on_done_refused(org):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-14")
    res1 = _submit(org.o1, rec, "KQ-ONLY").result
    rec.refresh_from_db()
    assert rec.status == RecordStatus.DONE
    with pytest.raises(ValidationError):
        services.revoke_result_reference(org.o1, rec.pk, res1.pk, "Hủy")
    # correction is the allowed path
    services.correct_result_reference(org.o1, rec.pk, res1.pk, "KQ-REPL", "Sai số")
    rec.refresh_from_db()
    assert rec.status == RecordStatus.DONE and rec.completed_at is not None


@pytest.mark.django_db
def test_revoke_allowed_when_other_effective_results(org):
    rec = make_record(org.leader, org.d1, [org.o1], ref="OPS-15")
    r1 = _submit(org.o1, rec, "KQ-A").result
    _submit(org.o1, rec, "KQ-B")
    services.revoke_result_reference(org.o1, rec.pk, r1.pk, "Nộp nhầm")
    r1.refresh_from_db()
    assert r1.effective_status == "Đã hủy hiệu lực"
    assert AuditEvent.objects.filter(record=rec, action="result.revoked").exists()


@pytest.mark.django_db
def test_correction_only_by_original_submitter_active_assignee(org):
    rec = make_record(org.leader, org.d1, [org.o1, org.o1b], ref="OPS-16")
    res1 = _submit(org.o1, rec, "KQ-C").result
    with pytest.raises(PermissionDenied):
        services.correct_result_reference(org.o1b, rec.pk, res1.pk, "KQ-X", "x")  # not submitter
    with pytest.raises(PermissionDenied):
        services.correct_result_reference(org.leader, rec.pk, res1.pk, "KQ-X", "x")  # not assignee
    # hồ sơ DONE không sửa assignment qua service; giả lập thu hồi trực tiếp
    # (mất assignee cũng mất quyền xem → deny-by-default trả DoesNotExist)
    rec.assignees.filter(user=org.o1).update(is_active=False)
    with pytest.raises((PermissionDenied, WorkRecord.DoesNotExist)):
        services.correct_result_reference(org.o1, rec.pk, res1.pk, "KQ-X", "x")


@pytest.mark.django_db
def test_concurrent_correction_single_winner(org_tx):
    import threading

    from django.db import connections

    o = org_tx
    rec = make_record(o.leader, o.d1, [o.o1], ref="OPS-17")
    res1 = services.submit_result_reference(o.o1, rec.pk, "KQ-T").result

    results, barrier = {}, threading.Barrier(2)

    def try_correct(i, code):
        try:
            barrier.wait(10)
            services.correct_result_reference(o.o1, rec.pk, res1.pk, code, "race")
            results[i] = "ok"
        except ValidationError:
            results[i] = "conflict"
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=try_correct, args=(0, "KQ-T1")),
        threading.Thread(target=try_correct, args=(1, "KQ-T2")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(results.values()) == ["conflict", "ok"]
    assert ResultCorrection.objects.filter(result=res1).count() == 1
    assert WorkRecord.objects.get(pk=rec.pk).results.filter(corrections__isnull=True).count() == 1
