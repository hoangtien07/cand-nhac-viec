"""A02 IDOR, A03 technical admin, A08/A09/A10 scopes, A23 list/report leak."""

import pytest

from apps.records.models import ResultReference, WorkRecord

from .conftest import make_record

pytestmark = pytest.mark.django_db


@pytest.fixture
def recs(org):
    return {
        "a1": make_record(org.o1, org.d1, [org.o1, org.o1b], watchers=[org.o2], ref="A-1"),
        "a2_with_sub": make_record(org.leader, org.d2, [org.o2, org.o1c], ref="A-2"),
        "a2_only": make_record(org.mgr2, org.d2, [org.o2b], ref="A-3"),
        "b": make_record(org.b1, org.d3, [org.b1], ref="B-SECRET-1"),
    }


def test_cross_unit_get_and_post_are_404_and_no_write(org, recs, client_for):
    c = client_for(org.o1)
    b = recs["b"]
    assert c.get(f"/ho-so/{b.pk}/").status_code == 404
    for path, data in [
        ("nop/", {"code": "X", "confirm": "1"}),
        ("nguoi-xu-ly/", {"assignees": [org.o1.pk]}),
        ("theo-doi/", {"watchers": [org.o1.pk]}),
        ("han/", {"due_date": "2099-01-01"}),
    ]:
        assert c.post(f"/ho-so/{b.pk}/{path}", data).status_code == 404
    # nonexistent id behaves the same as foreign id
    assert c.get("/ho-so/00000000-0000-0000-0000-000000000000/").status_code == 404
    assert not ResultReference.objects.filter(record=b).exists()


def test_cross_unit_leader_sees_nothing_and_search_does_not_leak(org, recs, client_for):
    c = client_for(org.bleader)
    body = c.get("/ho-so/?q=A-").content.decode()
    assert "A-1" not in body and "A-2" not in body
    assert c.get(f"/ho-so/{recs['a1'].pk}/").status_code == 404
    rep = c.get("/bao-cao/").content.decode()
    assert "Phòng 1" not in rep


def test_technical_admin_denied_business_but_manages_users(org, recs, client_for):
    c = client_for(org.admin)
    for url in ["/ho-so/", f"/ho-so/{recs['a1'].pk}/", "/bao-cao/", "/thong-bao/", "/ho-so/tao/"]:
        assert c.get(url).status_code == 403, url
    assert c.post(f"/ho-so/{recs['a1'].pk}/nop/", {"code": "X", "confirm": "1"}).status_code == 403
    assert c.get("/quan-tri/").status_code == 200
    assert "B-SECRET" not in c.get("/quan-tri/").content.decode()


def test_superuser_flags_grant_nothing(org, recs, client_for):
    org.o2b.is_staff = org.o2b.is_superuser = True
    org.o2b.save()
    c = client_for(org.o2b)
    assert c.get(f"/ho-so/{recs['a1'].pk}/").status_code == 404
    assert c.get("/admin/").status_code == 404


def test_business_user_cannot_use_admin_panel(org, client_for):
    assert client_for(org.leader).get("/quan-tri/").status_code == 403


def test_manager_scope(org, recs, client_for):
    m1 = client_for(org.mgr1)
    assert m1.get(f"/ho-so/{recs['a1'].pk}/").status_code == 200  # A08 own dept
    assert m1.get(f"/ho-so/{recs['a2_with_sub'].pk}/").status_code == 200  # A09 subordinate assigned
    assert m1.get(f"/ho-so/{recs['a2_only'].pk}/").status_code == 404  # A09 not in scope
    m2 = client_for(org.mgr2)
    assert m2.get(f"/ho-so/{recs['a1'].pk}/").status_code == 404  # other manager, no share


def test_officer_scope_and_leader_whole_unit(org, recs, client_for):
    o1b = client_for(org.o1b)
    assert o1b.get(f"/ho-so/{recs['a1'].pk}/").status_code == 200
    assert o1b.get(f"/ho-so/{recs['a2_with_sub'].pk}/").status_code == 404
    ld = client_for(org.leader)
    for k in ("a1", "a2_with_sub", "a2_only"):
        assert ld.get(f"/ho-so/{recs[k].pk}/").status_code == 200
    assert ld.get(f"/ho-so/{recs['b'].pk}/").status_code == 404


def test_watcher_reads_but_cannot_mutate(org, recs, client_for):
    rec = recs["a1"]
    c = client_for(org.o2)
    body = c.get(f"/ho-so/{rec.pk}/").content.decode()
    assert "A-1" in body and "Nộp số hiệu kết quả" not in body
    assert c.post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-W", "confirm": "1"}).status_code == 403
    assert c.post(f"/ho-so/{rec.pk}/han/", {"due_date": "2099-01-01"}).status_code == 403
    assert c.post(f"/ho-so/{rec.pk}/nguoi-xu-ly/", {"assignees": [org.o2.pk]}).status_code == 403
    rec.refresh_from_db()
    assert rec.status == "OPEN" and not rec.results.exists()


def test_leader_who_is_not_assignee_cannot_submit(org, recs, client_for):
    c = client_for(org.leader)
    assert c.post(f"/ho-so/{recs['a1'].pk}/nop/", {"code": "KQ-L", "confirm": "1"}).status_code == 403


def test_reports_counts_only_scope(org, recs, client_for):
    from django.utils import timezone

    from apps.reports.views import report_summary

    totals, _ = report_summary(org.leader, timezone.now())
    assert totals["open"] == 3
    totals, _ = report_summary(org.mgr2, timezone.now())
    assert totals["open"] == 2
    totals, _ = report_summary(org.o2, timezone.now())  # assignee of A-2; watcher-only A-1 not counted
    assert totals["open"] == 1
    totals, _ = report_summary(org.b1, timezone.now())
    assert totals["open"] == 1
    assert WorkRecord.objects.count() == 4


def test_notification_of_other_user_is_404(org, recs, client_for):
    import datetime

    from apps.notifications.models import Notification
    from apps.notifications.services import remind_record
    from apps.records.timeutils import db_now

    remind_record(recs["a1"].pk, now=db_now() + datetime.timedelta(days=2))
    n = Notification.objects.filter(recipient=org.o1).first()
    assert n is not None
    assert client_for(org.o1b).post(f"/thong-bao/{n.pk}/da-doc/").status_code == 404
    assert client_for(org.b1).post(f"/thong-bao/{n.pk}/da-doc/").status_code == 404
