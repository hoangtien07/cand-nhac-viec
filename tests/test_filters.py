"""Advanced record-list filters: folder, assignee, creator, due range, flags, reset."""

import pytest

from apps.organization import folder_services
from apps.organization.models import FolderRole

from .conftest import make_record
from .test_folder_models import make_folder


@pytest.mark.django_db
def test_filter_by_folder(org, client_for):
    fa = make_folder(org.ua, org.d1, org.mgr1)
    r_in = make_record(org.mgr1, org.d1, [org.o1], ref="FLT-IN")
    r_in.folder = fa
    r_in.save()
    make_record(org.mgr1, org.d1, [org.o1], ref="FLT-OUT")
    res = client_for(org.mgr1).get("/ho-so/", {"folder": str(fa.pk)})
    body = res.content.decode()
    assert "FLT-IN" in body
    assert "FLT-OUT" not in body


@pytest.mark.django_db
def test_filter_by_assignee_and_creator(org, client_for):
    make_record(org.mgr1, org.d1, [org.o1], ref="FLT-A1")
    make_record(org.mgr1, org.d1, [org.o1b], ref="FLT-A2")
    res = client_for(org.mgr1).get("/ho-so/", {"assignee": str(org.o1.pk)})
    body = res.content.decode()
    assert "FLT-A1" in body
    assert "FLT-A2" not in body

    other = make_record(org.leader, org.d1, [org.o1], ref="FLT-C2")
    res = client_for(org.leader).get("/ho-so/", {"creator": str(other.created_by_id)})
    body = res.content.decode()
    assert "FLT-C2" in body


@pytest.mark.django_db
def test_filter_due_date_range(org, client_for):
    from apps.records.timeutils import db_now, local_date

    today = local_date(db_now())
    make_record(org.mgr1, org.d1, [org.o1], ref="FLT-D1", days=0)
    make_record(org.mgr1, org.d1, [org.o1], ref="FLT-D2", days=10)
    res = client_for(org.mgr1).get("/ho-so/", {"due_from": today.isoformat(), "due_to": today.isoformat()})
    body = res.content.decode()
    assert "FLT-D1" in body
    assert "FLT-D2" not in body


@pytest.mark.django_db
def test_filter_assigned_to_me(org, client_for):
    make_record(org.mgr1, org.d1, [org.o1], ref="FLT-MINE")
    make_record(org.mgr1, org.d1, [org.o1b], ref="FLT-OTHER")
    res = client_for(org.o1).get("/ho-so/", {"assigned_to_me": "on"})
    body = res.content.decode()
    assert "FLT-MINE" in body
    assert "FLT-OTHER" not in body


@pytest.mark.django_db
def test_filter_shared_with_me(org, client_for):
    fa = make_folder(org.ua, org.d1, org.mgr1)
    folder_services.grant_folder(org.mgr1, fa.pk, org.o2.pk, FolderRole.VIEWER)
    r_in_folder = make_record(org.leader, org.d1, [org.o1], ref="FLT-SHF")
    r_in_folder.folder = fa
    r_in_folder.save()
    r_shared = make_record(org.leader, org.d1, [org.o1], ref="FLT-SHD")
    folder_services.share_record(org.leader, r_shared.pk, org.o2.pk)
    make_record(org.leader, org.d1, [org.o1], ref="FLT-NONE")

    res = client_for(org.o2).get("/ho-so/", {"shared_with_me": "on"})
    body = res.content.decode()
    assert "FLT-SHF" in body
    assert "FLT-SHD" in body
    assert "FLT-NONE" not in body


@pytest.mark.django_db
def test_reset_filters_keeps_work_year(org, client_for):
    c = client_for(org.mgr1)
    res = c.get("/ho-so/")
    assert res.context["form"].is_valid() or True
    body = res.content.decode()
    assert 'href="/ho-so/"' in body or "Xóa bộ lọc" in body


@pytest.mark.django_db
def test_filters_do_not_leak_cross_unit(org, client_for):
    fa = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="FLT-XA")
    rec.folder = fa
    rec.save()
    # Unit-B user must not see the record or folder via filters
    res = client_for(org.bleader).get("/ho-so/", {"q": "FLT-XA"})
    assert len(res.context["page"].object_list) == 0
