"""A11, A12, A14, A15, A16, A17 + immutability."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditEvent
from apps.records import services
from apps.records.models import ResultReference
from apps.records.timeutils import db_now

from .conftest import make_record

pytestmark = pytest.mark.django_db


@pytest.fixture
def rec(org):
    return make_record(org.leader, org.d1, [org.o1, org.o1b, org.o2], watchers=[org.o2b])


def test_direct_submit_closes_record(org, rec, client_for):
    c = client_for(org.o1)
    r = c.post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-001"}, follow=True)
    assert "Hồ sơ đã HOÀN THÀNH" in r.content.decode()
    rec.refresh_from_db()
    assert rec.status == "DONE" and rec.completed_by == org.o1 and rec.completed_at is not None
    assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1
    assert AuditEvent.objects.filter(record=rec, action="result.submitted").count() == 1


def test_htmx_submit_returns_client_redirect(org, rec, client_for):
    c = client_for(org.o1)
    r = c.post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-H", "confirm": "1"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and r["HX-Redirect"] == f"/ho-so/{rec.pk}/"


def test_additional_results_after_done_keep_completion(org, rec):
    services.submit_result_reference(org.o1, rec.pk, "KQ-1")
    rec.refresh_from_db()
    at, by = rec.completed_at, rec.completed_by_id
    out = services.submit_result_reference(org.o2, rec.pk, "KQ-2")
    out3 = services.submit_result_reference(org.o1b, rec.pk, "KQ-3")
    assert out.created and not out.completed_record and out3.created
    rec.refresh_from_db()
    assert (rec.completed_at, rec.completed_by_id, rec.status) == (at, by, "DONE")
    assert rec.results.count() == 3
    assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1
    assert AuditEvent.objects.filter(record=rec, action="result.submitted").count() == 3


@pytest.mark.parametrize("variant", ["KQ-2026-001", "kq-2026-001 ", "  KQ-2026-001", "ＫＱ-2026-001"])
def test_duplicate_normalized_code_is_idempotent(org, rec, variant):
    services.submit_result_reference(org.o1, rec.pk, "KQ-2026-001")
    out = services.submit_result_reference(org.o1b, rec.pk, variant)
    assert out.created is False
    assert ResultReference.objects.filter(record=rec).count() == 1
    assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1
    assert AuditEvent.objects.filter(record=rec, action="result.submitted").count() == 1


def test_retry_post_same_code_via_ui(org, rec, client_for):
    c = client_for(org.o1)
    for _ in range(3):
        c.post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-R", "confirm": "1"})
    assert rec.results.count() == 1


@pytest.mark.parametrize("bad", ["", "   ", "x" * 65, "KQ\x00001", "KQ<script>", "KQ\n1"])
def test_invalid_codes_rejected_and_record_stays_open(org, rec, client_for, bad):
    c = client_for(org.o1)
    r = c.post(f"/ho-so/{rec.pk}/nop/", {"code": bad, "confirm": "1"})
    assert r.status_code == 400
    with pytest.raises(ValidationError):
        services.submit_result_reference(org.o1, rec.pk, bad)
    rec.refresh_from_db()
    assert rec.status == "OPEN" and not rec.results.exists()


def test_revoked_assignee_denied_on_stale_page(org, rec, client_for):
    c = client_for(org.o1b)
    assert "Nộp số hiệu kết quả" in c.get(f"/ho-so/{rec.pk}/").content.decode()
    services.update_assignment(org.leader, rec.pk, [org.o1, org.o2])
    r = c.post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-STALE", "confirm": "1"})
    assert r.status_code in (403, 404)
    with pytest.raises((PermissionDenied, type(rec).DoesNotExist)):
        services.submit_result_reference(org.o1b, rec.pk, "KQ-STALE")
    assert not rec.results.exists()


def test_deactivated_user_cannot_submit(org, rec):
    org.o1.is_active = False
    org.o1.save()
    with pytest.raises((PermissionDenied, type(rec).DoesNotExist)):
        services.submit_result_reference(org.o1, rec.pk, "KQ-X")


def test_timestamps_from_db_and_browser_timestamp_ignored(org, rec, client_for):
    before = db_now()
    c = client_for(org.o1)
    c.post(
        f"/ho-so/{rec.pk}/nop/",
        {
            "code": "KQ-T",
            "confirm": "1",
            "submitted_at": "2000-01-01T00:00:00Z",
            "completed_at": "2000-01-01",
        },
    )
    after = db_now()
    rec.refresh_from_db()
    res = rec.results.get()
    assert before <= res.submitted_at <= after
    assert before <= rec.completed_at <= after
    ev = AuditEvent.objects.get(record=rec, action="record.completed")
    assert before <= ev.created_at <= after
    body = c.get(f"/ho-so/{rec.pk}/").content.decode()
    from django.utils import timezone

    assert timezone.localtime(res.submitted_at).strftime("%d/%m/%Y %H:%M:%S") in body  # Asia/Ho_Chi_Minh


def test_result_audit_and_completion_are_immutable_in_db(org, rec):
    services.submit_result_reference(org.o1, rec.pk, "KQ-IMM")
    res = rec.results.get()
    for sql in (
        "UPDATE records_resultreference SET code='X' WHERE id=%s",
        "DELETE FROM records_resultreference WHERE id=%s",
    ):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [res.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("DELETE FROM audit_auditevent WHERE record_id=%s", [rec.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("UPDATE audit_auditevent SET action='x' WHERE record_id=%s", [rec.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            "UPDATE records_workrecord SET completed_at=now() - interval '1 day' WHERE id=%s", [rec.pk]
        )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            "UPDATE records_workrecord SET status='OPEN', completed_at=NULL, completed_by_id=NULL "
            "WHERE id=%s",
            [rec.pk],
        )
    with pytest.raises(PermissionError):
        AuditEvent.objects.filter(record=rec).delete()
    with pytest.raises(PermissionError):
        AuditEvent.objects.filter(record=rec).update(action="x")
