"""A04–A07 create/assign/deadline + A24 audit (STT2: watchers UI retired)."""

import datetime

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditEvent
from apps.records import services
from apps.records.models import RecordAssignee, RecordWatcher, WorkRecord

from .conftest import make_record, today

pytestmark = pytest.mark.django_db


def _form(org, **kw):
    data = {
        "task_kind": "DOCUMENT",
        "reference_no": "CV-10/2026",
        "owner_department": org.d1.pk,
        "due_date": (today() + datetime.timedelta(days=2)).isoformat(),
        "assignees": [org.o1.pk, org.o1b.pk],
    }
    data.update(kw)
    return data


def test_officer_creates_in_own_dept_via_ui(org, client_for):
    c = client_for(org.o1)
    r = c.post("/ho-so/tao/", _form(org, watchers=[org.o2.pk]))
    assert r.status_code == 302
    rec = WorkRecord.objects.get()
    assert (rec.assigner, rec.created_by, rec.unit, rec.status) == (org.o1, org.o1, org.ua, "OPEN")
    assert rec.created_at is not None
    ev = AuditEvent.objects.get(record=rec, action="record.created")
    assert ev.actor == org.o1
    # deadline 23:59:59 Vietnam time (H04)
    local = rec.due_at.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
    assert (local.hour, local.minute, local.second) == (23, 59, 59)


def test_officer_cannot_assign_other_dept(org, client_for):
    c = client_for(org.o1)
    r = c.post("/ho-so/tao/", _form(org, assignees=[org.o1.pk, org.o2.pk]))
    assert r.status_code == 400
    assert WorkRecord.objects.count() == 0
    with pytest.raises(ValidationError):
        make_record(org.o1, org.d1, [org.o2])
    assert WorkRecord.objects.count() == 0


def test_officer_cannot_create_for_other_dept(org):
    with pytest.raises(PermissionDenied):
        make_record(org.o1, org.d2, [org.o1])


def test_past_deadline_and_blank_ref_rejected(org, client_for):
    c = client_for(org.o1)
    assert c.post("/ho-so/tao/", _form(org, due_date="2000-01-01")).status_code == 400
    assert c.post("/ho-so/tao/", _form(org, reference_no="   ")).status_code == 400
    assert c.post("/ho-so/tao/", _form(org, assignees=[])).status_code == 400
    assert WorkRecord.objects.count() == 0


def test_leader_assigns_two_departments_without_widening_scope(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1, org.o2])
    assert set(rec.assignees.values_list("user__username", flat=True)) == {"o1", "o2"}
    other = make_record(org.leader, org.d1, [org.o1b], ref="OTHER")
    assert client_for(org.o2).get(f"/ho-so/{other.pk}/").status_code == 404


def test_three_assignees_displayed_watchers_not_in_ui(org, client_for):
    """STT2: legacy watcher rows still exist (history) but are not rendered on the UI."""
    rec = make_record(org.leader, org.d1, [org.o1, org.o1b, org.o2], watchers=[org.mgr2, org.o2b])
    assert RecordAssignee.objects.filter(record=rec).count() == 3
    assert RecordWatcher.objects.filter(record=rec).count() == 2
    body = client_for(org.o1).get(f"/ho-so/{rec.pk}/").content.decode()
    for u in (org.o1, org.o1b, org.o2):
        assert u.full_name in body
    assert "Người theo dõi" not in body


def test_assignment_watchers_deadline_changes_are_audited_and_soft(org, client_for):
    rec = make_record(org.mgr1, org.d1, [org.o1, org.o1b])
    c = client_for(org.mgr1)
    assert c.post(f"/ho-so/{rec.pk}/nguoi-xu-ly/", {"assignees": [org.o1.pk, org.o1c.pk]}).status_code == 302
    # STT2: watcher management endpoint retired — 404 from UI/API.
    assert c.post(f"/ho-so/{rec.pk}/theo-doi/", {"watchers": [org.o2.pk]}).status_code == 404
    # legacy row still manageable via service only (no hard delete of history)
    services.update_watchers(org.mgr1, rec.pk, [org.o2])
    assert RecordWatcher.objects.filter(record=rec, user=org.o2, is_active=True).exists()
    new_day = today() + datetime.timedelta(days=9)
    assert c.post(f"/ho-so/{rec.pk}/han/", {"due_date": new_day.isoformat()}).status_code == 302
    removed = RecordAssignee.objects.get(record=rec, user=org.o1b)
    assert removed.is_active is False  # history kept, no hard delete
    actions = list(AuditEvent.objects.filter(record=rec).values_list("action", flat=True))
    for a in (
        "record.created",
        "record.assignment_changed",
        "record.watchers_changed",
        "record.deadline_changed",
    ):
        assert a in actions
    dl = AuditEvent.objects.get(record=rec, action="record.deadline_changed")
    assert dl.metadata["before"] != dl.metadata["after"] and dl.actor == org.mgr1


def test_officer_assignee_cannot_change_assignment_or_deadline(org, client_for):
    rec = make_record(org.mgr1, org.d1, [org.o1, org.o1b])
    c = client_for(org.o1b)
    assert c.post(f"/ho-so/{rec.pk}/nguoi-xu-ly/", {"assignees": [org.o1b.pk]}).status_code == 403
    assert c.post(f"/ho-so/{rec.pk}/han/", {"due_date": "2099-01-01"}).status_code == 403


def test_list_search_by_reference_and_result_code(org, client_for):
    rec = make_record(org.o1, org.d1, [org.o1], ref="CV-ABC/2026")
    services.submit_result_reference(org.o1, rec.pk, "KQ-XYZ-9")
    c = client_for(org.o1)
    assert "CV-ABC/2026" in c.get("/ho-so/?q=cv-abc").content.decode()
    assert "CV-ABC/2026" in c.get("/ho-so/?q=kq-xyz").content.decode()
    assert "CV-ABC/2026" in c.get("/ho-so/?q=abc", HTTP_HX_REQUEST="true").content.decode()
