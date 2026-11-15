"""Task 5: quick actions, shared status/pagination, work-year scope on list + report."""

import datetime
import re

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.records.models import WorkRecord
from apps.records.timeutils import VN_TZ, due_at_for_date
from apps.reports.views import report_summary

from .conftest import PW, make_record, today

pytestmark = pytest.mark.django_db


def _labels(resp):
    return [a["label"] for a in resp.context["quick_actions"]]


def test_quick_actions_hide_unauthorized_admin_and_create(org, client_for):
    labels = _labels(client_for(org.o1).get("/"))
    assert {"Tạo hồ sơ công việc", "Danh sách hồ sơ", "Nộp kết quả (số hiệu)", "Báo cáo thống kê"} <= set(
        labels
    )
    for who in ("leader", "mgr1", "o1"):
        body = client_for(getattr(org, who)).get("/").content.decode()
        assert "Quản lý người dùng" not in body and reverse("adminpanel:home") not in body
    nodept = User(username="nodept", full_name="Không phòng", unit=org.ua, role=Role.OFFICER)
    nodept.set_password(PW)
    nodept.save()
    resp = client_for(nodept).get("/")
    assert "Tạo hồ sơ công việc" not in _labels(resp)
    assert f'href="{reverse("records:create")}"' not in resp.content.decode()


def test_submit_shortcut_never_posts(org, client_for):
    body = client_for(org.o1).get("/").content.decode()
    quick = body.split('data-testid="quick-actions"', 1)[1]
    assert "<form" not in quick.split("</section>", 1)[0]
    submit = next(a for a in client_for(org.o1).get("/").context["quick_actions"] if a["icon"] == "upload")
    assert submit["href"].startswith(reverse("dashboard"))


def test_no_unimplemented_settings_links(org, client_for):
    for user in (org.o1, org.leader, org.admin):
        resp = client_for(user).get("/", follow=True)
        body = resp.content.decode()
        assert "Cấu hình hệ thống" not in body
        assert 'href="#"' not in body


def test_status_badges_correct_in_list_and_dashboard(org, client_for):
    rec = make_record(org.leader, org.d1, [org.o1], ref="BADGE-OVER")
    WorkRecord.objects.filter(pk=rec.pk).update(due_at=due_at_for_date(today() - datetime.timedelta(days=1)))
    c = client_for(org.o1)
    for url in ("/", reverse("records:list")):
        body = c.get(url).content.decode()
        row = body.split("BADGE-OVER", 1)[1].split("</tr>", 1)[0]
        assert "badge-overdue" in row and "Quá hạn" in row, url


def test_shared_pagination_preserves_query_state(org, client_for):
    for i in range(30):
        make_record(org.leader, org.d1, [org.o1], ref=f"PG A/B {i:02d}")
    resp = client_for(org.o1).get(reverse("records:list"), {"q": "PG A/B", "status": "OPEN"})
    nxt = resp.context["next_href"]
    assert "page=2" in nxt and "status=OPEN" in nxt and "q=PG+A%2FB" in nxt
    assert f'href="{reverse("records:list")}{nxt.replace("&", "&amp;")}"' in resp.content.decode()


def test_record_list_and_report_apply_same_work_year_scope(org, client_for):
    make_record(org.leader, org.d1, [org.o1], ref="NOW-1")
    old = make_record(org.leader, org.d1, [org.o1], ref="OLD-1")
    WorkRecord.objects.filter(pk=old.pk).update(
        created_at=datetime.datetime(today().year - 1, 5, 5, tzinfo=VN_TZ)
    )
    c = client_for(org.leader)

    def list_refs():
        body = c.get(reverse("records:list")).content.decode()
        return set(re.findall(r">((?:NOW|OLD)-1)</a>", body))

    assert list_refs() == {"NOW-1"}
    assert c.get(reverse("reports:report")).context["totals"]["total"] == 1
    c.post(reverse("records:set_work_year"), {"year": str(today().year - 1)})
    assert list_refs() == {"OLD-1"}
    assert c.get(reverse("reports:report")).context["totals"]["total"] == 1
    totals, _ = report_summary(org.leader, datetime.datetime.now(VN_TZ))
    assert totals["total"] == 2  # backward-compatible: no year → all years


def test_direct_record_detail_not_hidden_by_year(org, client_for):
    old = make_record(org.leader, org.d1, [org.o1], ref="OLD-DETAIL")
    WorkRecord.objects.filter(pk=old.pk).update(
        created_at=datetime.datetime(today().year - 3, 1, 2, tzinfo=VN_TZ)
    )
    assert client_for(org.o1).get(reverse("records:detail", args=[old.pk])).status_code == 200
    assert client_for(org.b1).get(reverse("records:detail", args=[old.pk])).status_code == 404
