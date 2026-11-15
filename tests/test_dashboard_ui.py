import datetime
import re

import pytest
from django.urls import reverse

from apps.records import services
from apps.records.models import WorkRecord
from apps.records.timeutils import VN_TZ, due_at_for_date

from .conftest import make_record, today

pytestmark = pytest.mark.django_db


def refs(body):
    return re.findall(r'data-testid="record-row" data-reference="([^"]+)"', body)


def get(client, **params):
    return client.get(reverse("dashboard"), params)


def _overdue(rec, days=2):
    WorkRecord.objects.filter(pk=rec.pk).update(
        due_at=due_at_for_date(today() - datetime.timedelta(days=days))
    )


def test_dashboard_uses_assigned_work_only(org, client_for):
    make_record(org.leader, org.d1, [org.o1], ref="MINE-1")
    make_record(org.o1, org.d1, [org.o1b], ref="CREATED-BY-ME")
    make_record(org.leader, org.d1, [org.o1b], watchers=[org.o1], ref="WATCHING")
    resp = get(client_for(org.o1))
    assert refs(resp.content.decode()) == ["MINE-1"]
    assert resp.context["counts"]["all"] == 1


def test_dashboard_counts_partition_all_once(org, client_for):
    _overdue(make_record(org.leader, org.d1, [org.o1], ref="P-OVERDUE"))
    make_record(org.leader, org.d1, [org.o1], ref="P-SOON", days=1)
    make_record(org.leader, org.d1, [org.o1, org.o1b, org.o1c], ref="P-PROC", days=6)
    done = make_record(org.leader, org.d1, [org.o1, org.o1b], ref="P-DONE", days=4)
    services.submit_result_reference(org.o1b, done.pk, "KQ-1")
    resp = get(client_for(org.o1))
    counts = resp.context["counts"]
    assert counts == {"all": 4, "overdue": 1, "due_soon": 1, "processing": 1, "done": 1}
    assert counts["all"] == sum(v for k, v in counts.items() if k != "all")
    assert refs(resp.content.decode()) == ["P-OVERDUE", "P-SOON", "P-PROC", "P-DONE"]
    for tab, expected in (
        ("overdue", "P-OVERDUE"),
        ("due_soon", "P-SOON"),
        ("processing", "P-PROC"),
        ("done", "P-DONE"),
    ):
        assert refs(get(client_for(org.o1), tab=tab).content.decode()) == [expected], tab
    body = resp.content.decode()
    for hook in ("overdue", "soon", "processing", "done"):
        assert f'data-testid="dashboard-kpi-{hook}"' in body


def test_done_never_in_overdue(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="DONE-LATE")
    services.submit_result_reference(org.o1, rec.pk, "KQ-LATE")
    _overdue(rec, days=10)
    resp = get(client_for(org.o1))
    assert resp.context["counts"]["overdue"] == 0 and resp.context["counts"]["done"] == 1
    assert refs(get(client_for(org.o1), tab="overdue").content.decode()) == []


def test_dashboard_respects_policy_under_year_and_search(org, client_for):
    make_record(org.leader, org.d1, [org.o1], ref="GL-1/2026")
    make_record(org.bleader, org.d3, [org.b1], ref="GL-1/2026")
    old = make_record(org.leader, org.d1, [org.o1], ref="GL-OLD")
    WorkRecord.objects.filter(pk=old.pk).update(
        created_at=datetime.datetime(today().year - 1, 6, 1, tzinfo=VN_TZ)
    )
    c = client_for(org.o1)
    resp = get(c, q="gl-1/2026")
    assert refs(resp.content.decode()) == ["GL-1/2026"]
    assert resp.context["page"].object_list[0].unit_id == org.ua.pk
    assert "GL-OLD" not in refs(get(c).content.decode())
    c.post(reverse("records:set_work_year"), {"year": str(today().year - 1)})
    assert refs(get(c).content.decode()) == ["GL-OLD"]
    assert refs(get(client_for(org.b1), q="GL-OLD").content.decode()) == []


def test_dashboard_search_by_result_code_does_not_leak(org, client_for):
    theirs = make_record(org.bleader, org.d3, [org.b1], ref="B-REC")
    services.submit_result_reference(org.b1, theirs.pk, "KQ-SECRET")
    mine = make_record(org.leader, org.d1, [org.o1], ref="A-REC")
    services.submit_result_reference(org.o1, mine.pk, "KQ-MINE")
    c = client_for(org.o1)
    assert refs(get(c, q="KQ-SECRET").content.decode()) == []
    assert refs(get(c, q="kq-mine").content.decode()) == ["A-REC"]


def test_dashboard_filter_preserves_state(org, client_for):
    for i in range(10):
        make_record(org.leader, org.d1, [org.o1], ref=f"ABC-{i:02d}", days=6)
    c = client_for(org.o1)
    resp = get(c, tab="processing", q="ABC")
    body = resp.content.decode()
    assert len(refs(body)) == 8
    nxt = resp.context["next_href"]
    assert "tab=processing" in nxt and "q=ABC" in nxt and "page=2" in nxt
    assert (
        "q=ABC" in resp.context["tab_links"][0]["href"]
        and "page=" not in resp.context["tab_links"][0]["href"]
    )
    page2 = c.get(reverse("dashboard") + nxt)
    assert len(refs(page2.content.decode())) == 2
    partial = c.get(reverse("dashboard") + nxt, headers={"HX-Request": "true", "HX-Target": "dashboard-work"})
    pbody = partial.content.decode()
    assert 'data-testid="app-header"' not in pbody
    assert refs(pbody) == refs(page2.content.decode())
    assert 'hx-push-url="true"' in body


def test_query_values_are_escaped_not_injected(org, client_for):
    body = get(client_for(org.o1), q='"><script>x</script>').content.decode()
    assert "<script>x</script>" not in body


def test_invalid_tab_defaults_to_all(org, client_for):
    make_record(org.leader, org.d1, [org.o1], ref="T-1")
    resp = get(client_for(org.o1), tab="evil')--")
    assert resp.context["tab"] == "all"
    assert refs(resp.content.decode()) == ["T-1"]


def test_empty_dashboard_renders_actionable_empty_state(org, client_for):
    c = client_for(org.o1)
    body = get(c).content.decode()
    assert 'data-testid="dashboard-empty"' in body
    assert f'href="{reverse("records:list")}"' in body
    make_record(org.leader, org.d1, [org.o1], ref="Z-1")
    body = get(c, q="nothing-matches").content.decode()
    assert 'data-testid="dashboard-empty"' in body and "Xóa bộ lọc" in body


def test_department_filter_is_scoped(org, client_for):
    make_record(org.leader, org.d1, [org.o1], ref="D1-REC")
    make_record(org.leader, org.d2, [org.o1, org.o2], ref="D2-REC")
    c = client_for(org.o1)
    assert refs(get(c, department=str(org.d2.pk)).content.decode()) == ["D2-REC"]
    assert sorted(refs(get(c, department=str(org.d3.pk)).content.decode())) == ["D1-REC", "D2-REC"]
    assert sorted(refs(get(c, department="not-a-uuid").content.decode())) == ["D1-REC", "D2-REC"]
