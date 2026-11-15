"""A13, A14, A22 on real PostgreSQL with independent connections (threads → separate connections)."""

import threading
import time

import pytest
from django.db import connection, connections, transaction

from apps.audit.models import AuditEvent
from apps.notifications.models import Notification
from apps.notifications.services import remind_record
from apps.records import services
from apps.records.models import ResultReference, WorkRecord

from .conftest import make_record

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]


def _run_parallel(fns, hold_record_id=None):
    """Start all fns at the same instant. If hold_record_id is given, a separate connection holds the
    row lock until every worker is verifiably waiting on it in pg_stat_activity, then releases."""
    results, errors = [None] * len(fns), []
    held, release = threading.Event(), threading.Event()
    barrier = threading.Barrier(len(fns))

    def holder():
        try:
            with transaction.atomic():
                WorkRecord.objects.select_for_update().get(pk=hold_record_id)
                held.set()
                release.wait(15)
        finally:
            connections.close_all()

    def worker(i, fn):
        try:
            if hold_record_id:
                held.wait(10)
            barrier.wait(10)
            results[i] = fn()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connections.close_all()

    threads = []
    if hold_record_id:
        threads.append(threading.Thread(target=holder))
    threads += [threading.Thread(target=worker, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    if hold_record_id:
        deadline = time.monotonic() + 10
        waiting = 0
        while time.monotonic() < deadline:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
                waiting = cur.fetchone()[0]
            if waiting >= len(fns):
                break
            time.sleep(0.05)
        release.set()
        assert waiting >= len(fns), f"workers not blocked on row lock (waiting={waiting})"
    for t in threads:
        t.join(30)
    return results, errors


def _pids_distinct():
    pids = set()

    def grab():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            pids.add(cur.fetchone()[0])

    _run_parallel([grab, grab])
    return pids


def test_threads_use_independent_pg_connections(org_tx):
    assert connection.vendor == "postgresql"
    assert len(_pids_distinct()) == 2


@pytest.mark.parametrize("hold", [True, False], ids=["lock-contended", "barrier"])
def test_concurrent_different_codes_one_completion(org_tx, hold):
    o = org_tx
    for i in range(1 if hold else 5):
        rec = make_record(o.leader, o.d1, [o.o1, o.o2], ref=f"RACE-{hold}-{i}")
        res, errors = _run_parallel(
            [
                lambda r=rec: services.submit_result_reference(o.o1, r.pk, "KQ-A"),
                lambda r=rec: services.submit_result_reference(o.o2, r.pk, "KQ-B"),
            ],
            hold_record_id=rec.pk if hold else None,
        )
        assert not errors, errors
        assert ResultReference.objects.filter(record=rec).count() == 2
        assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1
        assert sum(r.completed_record for r in res) == 1
        rec.refresh_from_db()
        winner = next(r for r in res if r.completed_record)
        assert rec.status == "DONE" and rec.completed_by_id == winner.result.submitted_by_id
        at, by = rec.completed_at, rec.completed_by_id
        services.submit_result_reference(o.o1, rec.pk, "KQ-C")
        rec.refresh_from_db()
        assert (rec.completed_at, rec.completed_by_id) == (at, by)
        assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1


@pytest.mark.parametrize("hold", [True, False], ids=["lock-contended", "barrier"])
def test_concurrent_same_code_one_result(org_tx, hold):
    o = org_tx
    for i in range(1 if hold else 5):
        rec = make_record(o.leader, o.d1, [o.o1, o.o2], ref=f"SAME-{hold}-{i}")
        res, errors = _run_parallel(
            [
                lambda r=rec: services.submit_result_reference(o.o1, r.pk, "KQ-SAME"),
                lambda r=rec: services.submit_result_reference(o.o2, r.pk, "kq-same "),
            ],
            hold_record_id=rec.pk if hold else None,
        )
        assert not errors, errors
        assert ResultReference.objects.filter(record=rec).count() == 1
        assert sum(r.created for r in res) == 1
        assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1
        assert AuditEvent.objects.filter(record=rec, action="result.submitted").count() == 1


def test_concurrent_http_posts(org_tx):
    from django.test import Client

    o = org_tx
    rec = make_record(o.leader, o.d1, [o.o1, o.o2], ref="HTTP-RACE")

    def post(user, code):
        def fn():
            c = Client(HTTP_HOST="localhost")
            c.force_login(user)
            return c.post(f"/ho-so/{rec.pk}/nop/", {"code": code, "confirm": "1"}).status_code

        return fn

    res, errors = _run_parallel([post(o.o1, "KQ-H1"), post(o.o2, "KQ-H2")], hold_record_id=rec.pk)
    assert not errors and res == [302, 302]
    assert ResultReference.objects.filter(record=rec).count() == 2
    assert AuditEvent.objects.filter(record=rec, action="record.completed").count() == 1


@pytest.mark.parametrize("hold", [True, False], ids=["lock-contended", "barrier"])
def test_scheduler_vs_submit_no_active_reminder_after_done(org_tx, hold):
    import datetime

    o = org_tx
    for i in range(1 if hold else 5):
        rec = make_record(o.mgr1, o.d1, [o.o1, o.o1b], ref=f"R2-{hold}-{i}")
        overdue_now = rec.due_at + datetime.timedelta(days=1, hours=2)
        _, errors = _run_parallel(
            [
                lambda r=rec, n=overdue_now: remind_record(r.pk, now=n),
                lambda r=rec: services.submit_result_reference(o.o1, r.pk, "KQ-R2"),
            ],
            hold_record_id=rec.pk if hold else None,
        )
        assert not errors, errors
        rec.refresh_from_db()
        assert rec.status == "DONE"
        assert not Notification.objects.filter(record=rec, resolved_at__isnull=True).exists()
    # history preserved: in at least one interleaving reminders may have been created and then resolved
    assert Notification.objects.filter(resolved_at__isnull=True).count() == 0


def test_scheduler_first_then_submit_keeps_history(org_tx):
    import datetime

    o = org_tx
    rec = make_record(o.mgr1, o.d1, [o.o1, o.o1b], ref="R2-ORDER")
    now = rec.due_at + datetime.timedelta(days=1)
    assert remind_record(rec.pk, now=now) == 3
    services.submit_result_reference(o.o1, rec.pk, "KQ-1")
    assert Notification.objects.filter(record=rec).count() == 3
    assert not Notification.objects.filter(record=rec, resolved_at__isnull=True).exists()
    assert remind_record(rec.pk, now=now + datetime.timedelta(days=1)) == 0
