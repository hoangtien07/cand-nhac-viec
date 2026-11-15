"""A18–A21 reminders (web-only, derived states, dedupe, none after DONE)."""

import datetime

import pytest
from django.core.management import call_command

from apps.notifications.models import Notification
from apps.notifications.services import remind_record, run_due_reminders
from apps.records import services
from apps.records.models import WorkRecord
from apps.records.timeutils import VN_TZ, due_at_for_date

from .conftest import make_record, today

pytestmark = pytest.mark.django_db


def at(day, hour=9):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=VN_TZ)


@pytest.fixture
def rec(org):
    return make_record(org.mgr1, org.d1, [org.o1, org.o1b], watchers=[org.o2], days=5)


def due(rec):
    return rec.due_at.astimezone(VN_TZ).date()


def test_no_reminder_far_from_deadline(rec):
    assert remind_record(rec.pk, now=at(due(rec) - datetime.timedelta(days=3))) == 0


def test_due_soon_d1_only_active_assignees(org, rec):
    assert remind_record(rec.pk, now=at(due(rec) - datetime.timedelta(days=1))) == 2
    ns = Notification.objects.filter(record=rec)
    assert set(ns.values_list("recipient__username", flat=True)) == {"o1", "o1b"}
    assert set(ns.values_list("type", flat=True)) == {"DUE_SOON"}


def test_due_today(rec):
    remind_record(rec.pk, now=at(due(rec)))
    assert set(Notification.objects.values_list("type", flat=True)) == {"DUE_TODAY"}


def test_overdue_includes_owner_manager_daily(org, rec):
    d1 = due(rec) + datetime.timedelta(days=1)
    assert remind_record(rec.pk, now=at(d1)) == 3
    assert set(Notification.objects.values_list("recipient__username", flat=True)) == {"o1", "o1b", "mgr1"}
    assert remind_record(rec.pk, now=at(d1 + datetime.timedelta(days=1))) == 3  # next day bucket
    assert Notification.objects.filter(type="OVERDUE").count() == 6


def test_deadline_boundary_2359_vn(rec):
    d = due(rec)
    edge = due_at_for_date(d)
    assert remind_record(rec.pk, now=edge) == 2
    assert set(Notification.objects.values_list("type", flat=True)) == {"DUE_TODAY"}
    # one second later (00:00:00 next day VN) → overdue: assignees + owner-department manager
    assert remind_record(rec.pk, now=edge + datetime.timedelta(seconds=1)) == 3
    assert Notification.objects.filter(type="OVERDUE").count() == 3


def test_repeated_runs_same_bucket_no_duplicates(org, rec):
    now = at(due(rec) + datetime.timedelta(days=1))
    run_due_reminders(now=now)
    run_due_reminders(now=now)
    remind_record(rec.pk, now=now)
    assert Notification.objects.count() == 3


def test_scheduler_skips_before_earliest_hour_unless_forced(rec):
    now = at(due(rec) + datetime.timedelta(days=1), hour=5)
    assert run_due_reminders(now=now)["skipped"] is True
    assert run_due_reminders(now=now, force=True)["created"] == 3


def test_no_reminder_after_done_and_existing_resolved(org, rec):
    now = at(due(rec) - datetime.timedelta(days=1))
    remind_record(rec.pk, now=now)
    assert Notification.objects.filter(resolved_at__isnull=True).count() == 2
    services.submit_result_reference(org.o1, rec.pk, "KQ-1")
    assert Notification.objects.filter(resolved_at__isnull=True).count() == 0
    assert Notification.objects.count() == 2  # history kept
    assert run_due_reminders(now=at(due(rec) + datetime.timedelta(days=2)))["created"] == 0
    assert Notification.objects.count() == 2


def test_removed_assignee_stops_receiving(org, rec):
    remind_record(rec.pk, now=at(due(rec) - datetime.timedelta(days=1)))
    services.update_assignment(org.mgr1, rec.pk, [org.o1])
    assert not Notification.objects.filter(recipient=org.o1b, resolved_at__isnull=True).exists()
    remind_record(rec.pk, now=at(due(rec)))
    assert not Notification.objects.filter(recipient=org.o1b, type="DUE_TODAY").exists()


def test_inbox_pending_hides_done_and_mark_read(org, rec, client_for):
    remind_record(rec.pk, now=at(due(rec) - datetime.timedelta(days=1)))
    c = client_for(org.o1)
    assert rec.reference_no in c.get("/thong-bao/").content.decode()
    n = Notification.objects.get(recipient=org.o1)
    assert c.post(f"/thong-bao/{n.pk}/da-doc/").status_code in (200, 302)
    n.refresh_from_db()
    assert n.read_at is not None
    services.submit_result_reference(org.o1, rec.pk, "KQ-1")
    assert rec.reference_no not in c.get("/thong-bao/?tab=pending").content.decode()
    assert rec.reference_no in c.get("/thong-bao/?tab=all").content.decode()


def test_management_command_runs(org):
    rec = make_record(org.o1, org.d1, [org.o1], days=0)
    call_command("send_due_reminders", "--force")
    assert Notification.objects.filter(record=rec, type="DUE_TODAY").count() == 1
    call_command("send_due_reminders", "--force")
    assert Notification.objects.filter(record=rec).count() == 1


def test_dashboard_derived_overdue_state(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1])
    WorkRecord.objects.filter(pk=rec.pk).update(due_at=due_at_for_date(today() - datetime.timedelta(days=2)))
    body = client_for(org.o1).get("/").content.decode()
    assert "Quá hạn (1)" in body
    from django.utils import timezone

    from apps.reports.views import report_summary

    totals, _ = report_summary(org.leader, timezone.now())
    assert totals["overdue"] == 1
    assert WorkRecord.objects.get(pk=rec.pk).status == "OPEN"  # no OVERDUE stored status
