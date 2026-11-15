import datetime

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.records import policies
from apps.records.models import WorkRecord
from apps.records.timeutils import VN_TZ
from apps.records.ui_state import SESSION_KEY, filter_created_in_work_year

from .conftest import make_record

pytestmark = pytest.mark.django_db


def _year():
    return timezone.now().astimezone(VN_TZ).year


def test_work_year_default_is_local_year(org, client_for):
    resp = client_for(org.o1).get("/")
    assert resp.context["active_work_year"] == _year()
    assert list(resp.context["work_year_choices"]) == list(range(_year() - 5, _year() + 2))
    assert 'data-testid="footer-work-year"' in resp.content.decode()


def test_work_year_vietnam_midnight_boundary(org):
    late = make_record(org.leader, org.d1, [org.o1], ref="Y-2026")
    early = make_record(org.leader, org.d1, [org.o1], ref="Y-2027")
    WorkRecord.objects.filter(pk=late.pk).update(
        created_at=datetime.datetime(2026, 12, 31, 23, 59, 59, tzinfo=VN_TZ)
    )
    WorkRecord.objects.filter(pk=early.pk).update(
        created_at=datetime.datetime(2027, 1, 1, 0, 0, tzinfo=VN_TZ)
    )
    qs = policies.visible_records_queryset(org.o1)
    assert set(filter_created_in_work_year(qs, 2026).values_list("reference_no", flat=True)) == {"Y-2026"}
    assert set(filter_created_in_work_year(qs, 2027).values_list("reference_no", flat=True)) == {"Y-2027"}


def test_work_year_post_requires_csrf_and_valid_integer(org, client_for):
    url = reverse("records:set_work_year")
    strict = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    strict.force_login(org.o1)
    assert strict.post(url, {"year": str(_year() - 1)}).status_code == 403
    c = client_for(org.o1)
    assert c.get(url).status_code == 405
    for bad in ("2026abc", "1900", "9999", "", str(_year() - 6), str(_year() + 2), "２０２６"):
        assert c.post(url, {"year": bad}).status_code == 400, bad
        assert SESSION_KEY not in c.session
    resp = c.post(url, {"year": str(_year() - 1)})
    assert resp.status_code == 302 and resp["Location"] == reverse("dashboard")
    assert c.session[SESSION_KEY] == _year() - 1


def test_year_post_redirect_is_same_origin_path_only(org, client_for):
    c = client_for(org.o1)
    url = reverse("records:set_work_year")
    resp = c.post(url, {"year": str(_year()), "next": "/bao-cao/?x=1"})
    assert resp["Location"] == "/bao-cao/"
    resp = c.post(url, {"year": str(_year()), "next": "https://evil.example/"})
    assert resp["Location"] == reverse("dashboard")


def test_year_switch_does_not_change_unit_or_department(org, client_for):
    c = client_for(org.o1)
    c.post(
        reverse("records:set_work_year"),
        {"year": str(_year() - 2), "unit": org.ub.pk, "department": org.d2.pk},
    )
    org.o1.refresh_from_db()
    assert (org.o1.unit_id, org.o1.department_id) == (org.ua.pk, org.d1.pk)


def test_year_selector_persists_in_session_across_navigation(org, client_for):
    c = client_for(org.o1)
    c.post(reverse("records:set_work_year"), {"year": str(_year() - 1)})
    for url in ("/", reverse("records:list"), reverse("reports:report")):
        resp = c.get(url)
        assert resp.context["active_work_year"] == _year() - 1, url
        assert f'<option value="{_year() - 1}" selected>' in resp.content.decode()


def test_tampered_session_year_falls_back(org, client_for):
    c = client_for(org.o1)
    s = c.session
    s[SESSION_KEY] = "2026; DROP"
    s.save()
    assert c.get("/").context["active_work_year"] == _year()


def test_sysadmin_has_no_year_selector(org, client_for):
    body = client_for(org.admin).get(reverse("adminpanel:home")).content.decode()
    assert 'data-testid="footer-work-year"' not in body
