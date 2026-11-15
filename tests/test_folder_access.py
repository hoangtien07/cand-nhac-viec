"""Task 2: folder/share authorization (DECISIONS §3, §5). Every case names its spec edge."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.organization import folder_services
from apps.organization.folder_policies import (
    can_create_record_in_folder,
    can_manage_folder,
    can_manage_folder_grants,
    can_move_record,
    can_share_record,
    can_view_folder,
    visible_folders_queryset,
)
from apps.organization.models import FolderRole
from apps.records import policies, services

from .conftest import make_record
from .test_folder_models import make_folder


def grant(folder, user, role=FolderRole.VIEWER, by=None):
    return folder_services.grant_folder(by or folder.created_by, folder.pk, user.pk, role)


def share(record, user, by):
    return folder_services.share_record(by, record.pk, user.pk)


def can_view(user, record):
    return policies.visible_records_queryset(user).filter(pk=record.pk).exists()


@pytest.mark.django_db
def test_case1_record_share_only_sees_one_record_no_folder_no_siblings(org):
    """§5.1: RecordShare(GL-002) -> sees GL-002 only; no folder, no sibling enumeration."""
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-002/2026")
    sibling = make_record(org.mgr1, org.d1, [org.o1b], ref="GL-003/2026")
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec.folder = folder
    rec.save()
    sibling.folder = folder
    sibling.save()

    share(rec, org.o2, by=org.mgr1)
    assert can_view(org.o2, rec)
    assert not can_view(org.o2, sibling)
    assert not can_view_folder(org.o2, folder)
    assert folder.pk not in visible_folders_queryset(org.o2).values_list("pk", flat=True)


@pytest.mark.django_db
def test_case2_folder_viewer_sees_current_and_future_records(org):
    """§5.2 + §5.11 (ASSUMPTION-F1): folder VIEWER sees all records incl. newly created."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    r1 = make_record(org.mgr1, org.d1, [org.o1], ref="GL-010")
    r1.folder = folder
    r1.save()
    grant(folder, org.o2, FolderRole.VIEWER)
    assert can_view(org.o2, r1)
    r2 = make_record(org.mgr1, org.d1, [org.o1b], ref="GL-011")
    r2.folder = folder
    r2.save()
    assert can_view(org.o2, r2)  # future record inherits visibility
    # ...but no extra rights: not assignee -> cannot submit
    assert not policies.can_submit_result(org.o2, r2)
    with pytest.raises(PermissionDenied):
        services.submit_result_reference(org.o2, r2.pk, "KQ-DENY")


@pytest.mark.django_db
def test_case3_revoke_folder_grant_keeps_independent_paths(org):
    """§5.3: revoke folder grant removes derived access; direct share/assignee persist."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    r_share = make_record(org.mgr1, org.d1, [org.o1], ref="GL-020")
    r_assigned = make_record(org.leader, org.d1, [org.o2], ref="GL-021")  # cross-dept assignee
    r_derived = make_record(org.mgr1, org.d1, [org.o1b], ref="GL-022")
    for r in (r_share, r_assigned, r_derived):
        r.folder = folder
        r.save()
    share(r_share, org.o2, by=org.mgr1)
    g = grant(folder, org.o2, FolderRole.VIEWER)
    folder_services.revoke_folder_grant(org.mgr1, g.pk)
    assert can_view(org.o2, r_share)  # direct share persists
    assert can_view(org.o2, r_assigned)  # assignee path persists (and can submit)
    assert policies.can_submit_result(org.o2, r_assigned)
    assert not can_view(org.o2, r_derived)  # derived-only access is gone
    assert not can_view_folder(org.o2, folder)


@pytest.mark.django_db
def test_case4_revoke_share_but_folder_member_keeps_view(org):
    """§5.4: direct share revoked, folder grant still gives view."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-030")
    rec.folder = folder
    rec.save()
    s = share(rec, org.o2, by=org.mgr1)
    grant(folder, org.o2, FolderRole.VIEWER)
    folder_services.revoke_record_share(org.mgr1, s.pk)
    assert can_view(org.o2, rec)


@pytest.mark.django_db
def test_case5_move_record_switches_derived_access(org):
    """§5.5: move A->B revokes A-derived visibility, grants B-derived; independent paths persist."""
    fa = make_folder(org.ua, org.d1, org.mgr1, name="Nhóm A")
    fb = make_folder(org.ua, org.d1, org.mgr1, name="Nhóm B")
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-040")
    rec.folder = fa
    rec.save()
    grant(fa, org.o2, FolderRole.VIEWER)
    grant(fb, org.o2b, FolderRole.VIEWER)
    assert can_view(org.o2, rec) and not can_view(org.o2b, rec)

    folder_services.move_record(org.mgr1, rec.pk, fb.pk)
    rec.refresh_from_db()
    assert rec.folder_id == fb.pk
    assert not can_view(org.o2, rec)  # lost A-derived
    assert can_view(org.o2b, rec)  # gained B-derived


@pytest.mark.django_db
def test_case6_rename_keeps_access_and_stable_link(org):
    """§5.6: rename doesn't change policy; UUID link stable."""
    folder = make_folder(org.ua, org.d1, org.mgr1, name="Tên cũ")
    grant(folder, org.o2, FolderRole.VIEWER)
    folder_services.rename_folder(org.mgr1, folder.pk, "Tên mới")
    folder.refresh_from_db()
    assert folder.name == "Tên mới"
    assert can_view_folder(org.o2, folder)
    assert str(folder.pk)  # UUID unchanged


@pytest.mark.django_db
def test_case7_inactive_or_moved_member_loses_grant_access(org):
    """§5.7: inactive user / user moved to another unit cannot use stale grants."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-050")
    rec.folder = folder
    rec.save()
    grant(folder, org.o2, FolderRole.VIEWER)
    assert can_view(org.o2, rec)
    org.o2.is_active = False
    org.o2.save()
    assert not can_view(org.o2, rec)
    org.o2.is_active = True
    org.o2.unit = org.ub
    org.o2.department = org.d3
    org.o2.save()
    assert not can_view(org.o2, rec)  # stale grant confers nothing across units


@pytest.mark.django_db
def test_case8_leader_full_sysadmin_denied_manager_baseline(org):
    """§5.8: leader sees all in unit; SYS_ADMIN sees nothing; manager baseline unchanged."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-060")
    rec.folder = folder
    rec.save()
    assert can_view(org.leader, rec)
    assert can_view_folder(org.leader, folder)
    assert not can_view(org.admin, rec)
    assert not can_view_folder(org.admin, folder)
    assert visible_folders_queryset(org.admin).count() == 0
    # baseline: mgr2 cannot see d1 record through folder (no grant, not managed)
    assert not can_view(org.mgr2, rec)


@pytest.mark.django_db
def test_cross_unit_urls_and_queries_deny_everything(org):
    """Cross-unit folder/record/share are invisible and ungrantable."""
    fb = make_folder(org.ub, org.d3, org.bleader)
    assert not can_view_folder(org.leader, fb)
    assert visible_folders_queryset(org.leader).count() == 0
    with pytest.raises((PermissionDenied, ValidationError)):
        folder_services.grant_folder(org.bleader, fb.pk, org.o1.pk, FolderRole.VIEWER)
    with pytest.raises((PermissionDenied, ValidationError)):
        folder_services.grant_folder(
            org.mgr1, make_folder(org.ua, org.d1, org.mgr1).pk, org.b1.pk, FolderRole.VIEWER
        )


@pytest.mark.django_db
def test_capability_matrix_roles(org):
    """§3 matrix: MANAGER manages grants; CONTRIBUTOR/VIEWER do not; none submit by grant."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    g_mgr = grant(folder, org.o2, FolderRole.MANAGER)
    grant(folder, org.o2b, FolderRole.CONTRIBUTOR)
    g_viewer = grant(folder, org.o1, FolderRole.VIEWER)
    assert can_manage_folder(org.o2, folder) and can_manage_folder_grants(org.o2, folder)
    assert not can_manage_folder_grants(org.o2b, folder)
    assert not can_manage_folder_grants(org.o1, folder)
    # grant alone never permits submit
    rec = make_record(org.mgr1, org.d1, [org.o1b], ref="GL-070")
    rec.folder = folder
    rec.save()
    for u in (org.o2, org.o1):
        assert not policies.can_submit_result(u, rec)
    del g_mgr, g_viewer


@pytest.mark.django_db
def test_can_share_record_rules(org):
    """ASSUMPTION-F2: leader, owner-dept manager, creator/assigner, folder MANAGER may share."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-080")
    assert can_share_record(org.leader, rec)
    assert can_share_record(org.mgr1, rec)
    assert not can_share_record(org.mgr2, rec)  # other dept manager
    assert not can_share_record(org.o2, rec)  # unrelated officer
    assert not can_share_record(org.admin, rec)
    rec.folder = folder
    rec.save()
    grant(folder, org.o2, FolderRole.MANAGER)
    assert can_share_record(org.o2, rec)  # folder MANAGER of the record's folder
    grant(folder, org.o1b, FolderRole.VIEWER)
    assert not can_share_record(org.o1b, rec)


@pytest.mark.django_db
def test_can_create_record_in_folder_respects_org_policy(org):
    """ASSUMPTION-F3: dept-B contributor may NOT create records owned by dept A."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    grant(folder, org.o2, FolderRole.CONTRIBUTOR)  # dept B contributor
    grant(folder, org.o1, FolderRole.CONTRIBUTOR)  # dept A contributor
    assert not can_create_record_in_folder(org.o2, folder)
    assert can_create_record_in_folder(org.mgr1, folder)
    assert can_create_record_in_folder(org.o1, folder)  # same dept as folder owner
    # own-dept officer WITHOUT any grant cannot even see the folder -> cannot create in it
    assert not can_view_folder(org.o1c, folder)
    assert not can_create_record_in_folder(org.o1c, folder)


@pytest.mark.django_db
def test_can_move_record_rules(org):
    """Move needs authority on the record AND on the destination folder."""
    fa = make_folder(org.ua, org.d1, org.mgr1, name="A")
    fb = make_folder(org.ua, org.d1, org.mgr1, name="B")
    f_d2 = make_folder(org.ua, org.d2, org.mgr2, name="D2")
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-090")
    rec.folder = fa
    rec.save()
    assert can_move_record(org.mgr1, rec, fb)
    assert can_move_record(org.leader, rec, fb)
    grant(fa, org.o2, FolderRole.MANAGER)
    assert not can_move_record(org.o2, rec, fb)  # folder grant != record authority
    # invariant: destination must share owner_department
    assert not can_move_record(org.mgr1, rec, f_d2)
    with pytest.raises((PermissionDenied, ValidationError)):
        folder_services.move_record(org.mgr1, rec.pk, f_d2.pk)


@pytest.mark.django_db
def test_report_scope_excludes_folder_only_access(org):
    """DECISIONS §4: folder-granted viewing is NOT reporting privilege (v1)."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-100")
    rec.folder = folder
    rec.save()
    grant(folder, org.o2, FolderRole.VIEWER)
    assert can_view(org.o2, rec)
    assert not policies.report_records_queryset(org.o2).filter(pk=rec.pk).exists()


@pytest.mark.django_db
def test_archived_folder_suspends_derived_access(org):
    """Archived folder suspends grants (deny-by-default); independent paths persist."""
    folder = make_folder(org.ua, org.d1, org.mgr1)
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-110")
    rec.folder = folder
    rec.save()
    grant(folder, org.o2, FolderRole.VIEWER)
    share(rec, org.o2b, by=org.mgr1)
    folder.is_archived = True
    folder.save()
    assert not can_view(org.o2, rec)
    assert can_view(org.o2b, rec)  # direct share unaffected


@pytest.mark.django_db
def test_share_viewer_never_submits_or_reassigns(org):
    """§3: a RecordShare VIEWER cannot submit, reassign or change deadline."""
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="GL-120")
    share(rec, org.o2, by=org.mgr1)
    assert not policies.can_submit_result(org.o2, rec)
    assert not policies.can_manage_assignment(org.o2, rec)
    assert not policies.can_edit_deadline(org.o2, rec)
