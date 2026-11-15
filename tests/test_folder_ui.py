"""Task 3: folder UI — scoped browsing, POST + CSRF mutations, 404 for out-of-scope."""

import pytest

from apps.organization import folder_services
from apps.organization.models import FolderGrant, FolderRole, WorkFolder
from apps.records.models import RecordShare

from .conftest import make_record
from .test_folder_models import make_folder


@pytest.mark.django_db
def test_folder_index_scoped_and_tabs(org, client_for):
    f_own = make_folder(org.ua, org.d1, org.mgr1, name="Nhóm phòng 1")
    make_folder(org.ua, org.d2, org.mgr2, name="Nhóm phòng 2")
    folder_services.grant_folder(org.mgr1, f_own.pk, org.o2.pk, FolderRole.VIEWER)

    c = client_for(org.o2)
    res = c.get("/nhom-ho-so/?tab=shared")
    assert res.status_code == 200 and "Nhóm phòng 1" in res.content.decode()
    res = c.get("/nhom-ho-so/?tab=all")
    body = res.content.decode()
    assert "Nhóm phòng 1" in body and "Nhóm phòng 2" not in body
    # unrelated officer sees an empty list everywhere
    c2 = client_for(org.o1c)
    for tab in ("mine", "shared", "all"):
        res = c2.get(f"/nhom-ho-so/?tab={tab}")
        assert res.status_code == 200
        assert "Chưa có nhóm hồ sơ" in res.content.decode()


@pytest.mark.django_db
def test_folder_detail_scoped_records_and_members(org, client_for):
    folder = make_folder(org.ua, org.d1, org.mgr1)
    r1 = make_record(org.mgr1, org.d1, [org.o1], ref="UI-01")
    r1.folder = folder
    r1.save()
    make_record(org.mgr1, org.d1, [org.o1b], ref="UI-02")  # unfiled sibling
    folder_services.grant_folder(org.mgr1, folder.pk, org.o2.pk, FolderRole.VIEWER)

    res = client_for(org.o2).get(f"/nhom-ho-so/{folder.pk}/")
    body = res.content.decode()
    assert res.status_code == 200 and "UI-01" in body and "UI-02" not in body
    assert org.o2.full_name in body  # member list visible to members
    # viewer cannot manage: no add-member form
    assert 'action="/nhom-ho-so/' not in body or "Thêm thành viên" not in body


@pytest.mark.django_db
def test_folder_detail_404_cross_unit_and_revoked(org, client_for):
    fb = make_folder(org.ub, org.d3, org.bleader)
    assert client_for(org.leader).get(f"/nhom-ho-so/{fb.pk}/").status_code == 404
    f = make_folder(org.ua, org.d1, org.mgr1)
    g = folder_services.grant_folder(org.mgr1, f.pk, org.o2.pk, FolderRole.VIEWER)
    folder_services.revoke_folder_grant(org.mgr1, g.pk)
    assert client_for(org.o2).get(f"/nhom-ho-so/{f.pk}/").status_code == 404


@pytest.mark.django_db
def test_create_folder_via_post_gives_creator_manager(org, client_for):
    c = client_for(org.o1)
    dept_pk = org.d1.pk
    res = c.post("/nhom-ho-so/tao/", {"name": "Nhóm mới", "owner_department": dept_pk})
    assert res.status_code == 302
    f = WorkFolder.objects.get(name="Nhóm mới")
    assert FolderGrant.objects.get(folder=f, user=org.o1).role == FolderRole.MANAGER
    # officer cannot create a folder for another department
    res = c.post("/nhom-ho-so/tao/", {"name": "Nhóm lạ", "owner_department": org.d2.pk})
    assert res.status_code == 400
    assert not WorkFolder.objects.filter(name="Nhóm lạ").exists()


@pytest.mark.django_db
def test_grant_and_revoke_via_post_csrf(org, client_for):
    folder = make_folder(org.ua, org.d1, org.mgr1)
    c = client_for(org.mgr1)
    res = c.post(
        f"/nhom-ho-so/{folder.pk}/thanh-vien/",
        {"user": org.o2.pk, "role": FolderRole.VIEWER},
    )
    assert res.status_code == 302
    g = FolderGrant.objects.get(folder=folder, user=org.o2)
    res = c.post(f"/nhom-ho-so/{folder.pk}/thanh-vien/{g.pk}/thu-hoi/")
    assert res.status_code == 302
    g.refresh_from_db()
    assert g.revoked_at is not None


@pytest.mark.django_db
def test_grant_post_requires_authority(org, client_for):
    folder = make_folder(org.ua, org.d1, org.mgr1)
    folder_services.grant_folder(org.mgr1, folder.pk, org.o2.pk, FolderRole.VIEWER)
    c = client_for(org.o2)  # viewer member, cannot manage grants
    res = c.post(f"/nhom-ho-so/{folder.pk}/thanh-vien/", {"user": org.o1c.pk, "role": "MANAGER"})
    assert res.status_code == 403
    assert not FolderGrant.objects.filter(folder=folder, user=org.o1c).exists()


@pytest.mark.django_db
def test_grant_post_requires_csrf(org, client_for):
    from django.test import Client

    folder = make_folder(org.ua, org.d1, org.mgr1)
    c = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    c.force_login(org.mgr1)
    res = c.post(f"/nhom-ho-so/{folder.pk}/thanh-vien/", {"user": org.o1c.pk, "role": "VIEWER"})
    assert res.status_code == 403


@pytest.mark.django_db
def test_member_list_excludes_revoked(org, client_for):
    folder = make_folder(org.ua, org.d1, org.mgr1)
    g = folder_services.grant_folder(org.mgr1, folder.pk, org.o2.pk, FolderRole.VIEWER)
    folder_services.revoke_folder_grant(org.mgr1, g.pk)
    res = client_for(org.mgr1).get(f"/nhom-ho-so/{folder.pk}/")
    assert org.o2.pk not in [gr.user_id for gr in res.context["grants"]]


@pytest.mark.django_db
def test_record_share_via_detail_post(org, client_for):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="UI-10")
    assert client_for(org.o2).get(f"/ho-so/{rec.pk}/").status_code == 404
    res = client_for(org.mgr1).post(f"/ho-so/{rec.pk}/chia-se/", {"user": org.o2.pk})
    assert res.status_code == 302
    assert client_for(org.o2).get(f"/ho-so/{rec.pk}/").status_code == 200
    s = RecordShare.objects.get(record=rec, user=org.o2)
    res = client_for(org.mgr1).post(f"/ho-so/{rec.pk}/chia-se/{s.pk}/thu-hoi/")
    assert res.status_code == 302
    assert client_for(org.o2).get(f"/ho-so/{rec.pk}/").status_code == 404


@pytest.mark.django_db
def test_move_record_via_detail_post(org, client_for):
    fa = make_folder(org.ua, org.d1, org.mgr1, name="A")
    fb = make_folder(org.ua, org.d1, org.mgr1, name="B")
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="UI-11")
    res = client_for(org.mgr1).post(f"/ho-so/{rec.pk}/nhom/", {"folder": fb.pk})
    assert res.status_code == 302
    rec.refresh_from_db()
    assert rec.folder_id == fb.pk
    # a viewer cannot move the record
    folder_services.grant_folder(org.mgr1, fa.pk, org.o2.pk, FolderRole.VIEWER)
    folder_services.move_record(org.mgr1, rec.pk, fa.pk)
    res = client_for(org.o2).post(f"/ho-so/{rec.pk}/nhom/", {"folder": fb.pk})
    assert res.status_code == 403
    rec.refresh_from_db()
    assert rec.folder_id == fa.pk


@pytest.mark.django_db
def test_record_detail_shows_folder_and_access_reason(org, client_for):
    folder = make_folder(org.ua, org.d1, org.mgr1, name="Nhóm Kế hoạch")
    rec = make_record(org.leader, org.d1, [org.o2], ref="UI-12")  # cross-dept assignee
    rec.folder = folder
    rec.save()
    body = client_for(org.o2).get(f"/ho-so/{rec.pk}/").content.decode()
    assert "Nhóm Kế hoạch" in body
    assert "được giao" in body  # access reason rendered


@pytest.mark.django_db
def test_sidebar_has_folder_nav_for_business_only(org, client_for):
    body = client_for(org.o1).get("/").content.decode()
    assert "Nhóm hồ sơ" in body and "/nhom-ho-so/" in body
    body = client_for(org.admin).get("/quan-tri/").content.decode()
    assert "/nhom-ho-so/" not in body
    # sysadmin hitting the folder area directly gets 403
    assert client_for(org.admin).get("/nhom-ho-so/").status_code == 403
