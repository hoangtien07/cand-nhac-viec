"""Task 1: folder/share model invariants (DECISIONS §2, ADR-002). Same-unit hard boundary."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.organization.models import FolderGrant, FolderRole, WorkFolder
from apps.records.models import RecordShare, ShareAccess

from .conftest import make_record


def make_folder(unit, dept, creator, name="Nhóm A", **kw):
    return WorkFolder.objects.create(unit=unit, owner_department=dept, name=name, created_by=creator, **kw)


@pytest.mark.django_db
def test_folder_same_unit_valid(org):
    f = make_folder(org.ua, org.d1, org.mgr1)
    assert f.pk and f.unit_id == org.ua.pk


@pytest.mark.django_db
def test_folder_owner_department_other_unit_rejected_clean_and_db(org):
    f = WorkFolder(unit=org.ua, owner_department=org.d3, name="X", created_by=org.leader)
    with pytest.raises(ValidationError):
        f.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        f.save()  # DB trigger must also reject


@pytest.mark.django_db
def test_duplicate_active_folder_name_same_department_rejected(org):
    make_folder(org.ua, org.d1, org.mgr1, name="Nhóm Trùng")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_folder(org.ua, org.d1, org.o1, name="nhóm   trùng")
    # same name in a different department is allowed
    make_folder(org.ua, org.d2, org.mgr2, name="Nhóm Trùng")


@pytest.mark.django_db
def test_archived_folder_frees_name(org):
    f = make_folder(org.ua, org.d1, org.mgr1, name="Nhóm Cũ")
    f.is_archived = True
    f.save()
    make_folder(org.ua, org.d1, org.mgr1, name="Nhóm Cũ")


@pytest.mark.django_db
def test_grant_unique_active_and_revoke_keeps_history(org):
    f = make_folder(org.ua, org.d1, org.mgr1)
    g = FolderGrant.objects.create(folder=f, user=org.o2, role=FolderRole.VIEWER, granted_by=org.mgr1)
    with pytest.raises(IntegrityError), transaction.atomic():
        FolderGrant.objects.create(folder=f, user=org.o2, role=FolderRole.MANAGER, granted_by=org.mgr1)
    g.revoke()
    g2 = FolderGrant.objects.create(folder=f, user=org.o2, role=FolderRole.MANAGER, granted_by=org.mgr1)
    assert FolderGrant.objects.filter(folder=f, user=org.o2).count() == 2
    assert g.revoked_at is not None and g2.is_active


@pytest.mark.django_db
def test_grant_cross_unit_user_rejected_clean_and_db(org):
    f = make_folder(org.ua, org.d1, org.mgr1)
    g = FolderGrant(folder=f, user=org.b1, role=FolderRole.VIEWER, granted_by=org.mgr1)
    with pytest.raises(ValidationError):
        g.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        g.save()


@pytest.mark.django_db
def test_record_folder_optional_and_same_owner_department(org):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="F-1")
    assert rec.folder_id is None
    f = make_folder(org.ua, org.d1, org.mgr1)
    rec.folder = f
    rec.save()
    rec.refresh_from_db()
    assert rec.folder_id == f.pk


@pytest.mark.django_db
def test_record_folder_other_department_rejected(org):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="F-2")
    f_other_dept = make_folder(org.ua, org.d2, org.mgr2)
    rec.folder = f_other_dept
    with pytest.raises(ValidationError):
        rec.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        rec.save()


@pytest.mark.django_db
def test_record_folder_other_unit_rejected_by_db(org):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="F-3")
    f_other_unit = make_folder(org.ub, org.d3, org.bleader)
    rec.folder = f_other_unit
    with pytest.raises(IntegrityError), transaction.atomic():
        rec.save()


@pytest.mark.django_db
def test_record_share_unique_active_and_revoke(org):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="F-4")
    s = RecordShare.objects.create(record=rec, user=org.o2, access=ShareAccess.VIEWER, granted_by=org.mgr1)
    with pytest.raises(IntegrityError), transaction.atomic():
        RecordShare.objects.create(record=rec, user=org.o2, access=ShareAccess.VIEWER, granted_by=org.mgr1)
    s.revoke()
    RecordShare.objects.create(record=rec, user=org.o2, access=ShareAccess.VIEWER, granted_by=org.mgr1)
    assert RecordShare.objects.filter(record=rec, user=org.o2).count() == 2


@pytest.mark.django_db
def test_record_share_cross_unit_rejected_clean_and_db(org):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="F-5")
    s = RecordShare(record=rec, user=org.b1, access=ShareAccess.VIEWER, granted_by=org.mgr1)
    with pytest.raises(ValidationError):
        s.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        s.save()


@pytest.mark.django_db
def test_grants_survive_member_timestamps_are_db(org):
    f = make_folder(org.ua, org.d1, org.mgr1)
    g = FolderGrant.objects.create(folder=f, user=org.o1, role=FolderRole.VIEWER, granted_by=org.mgr1)
    assert g.created_at is not None  # db_default Now(), not client input
    assert f.created_at is not None


@pytest.mark.django_db
def test_no_subfolders_one_record_one_folder(org):
    """v1: no recursive folders, record in at most one folder."""
    assert not hasattr(WorkFolder, "parent")
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="F-6")
    a, b = make_folder(org.ua, org.d1, org.mgr1, "A"), make_folder(org.ua, org.d1, org.mgr1, "B")
    rec.folder = a
    rec.save()
    rec.folder = b
    rec.save()
    rec.refresh_from_db()
    assert rec.folder_id == b.pk  # move replaces, never two folders
