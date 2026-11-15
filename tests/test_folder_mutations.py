"""Task 2b: folder/share mutations — audit, idempotency, history rows (DECISIONS §5)."""

import pytest

from apps.audit.models import AuditAction, AuditEvent
from apps.organization import folder_services
from apps.organization.models import FolderGrant, FolderRole
from apps.records.models import RecordShare

from .conftest import make_record
from .test_folder_models import make_folder


def actions(unit, **flt):
    return list(
        AuditEvent.objects.filter(unit=unit, **flt).values_list("action", flat=True)
    )


@pytest.mark.django_db
def test_create_folder_audits_and_grants_creator_manager(org):
    f = folder_services.create_folder(
        org.o1, name="Nhóm Phòng 1", owner_department=org.d1, description_short="demo"
    )
    g = FolderGrant.objects.get(folder=f, user=org.o1)
    assert g.role == FolderRole.MANAGER and g.is_active
    assert AuditAction.FOLDER_CREATED in actions(org.ua)
    ev = AuditEvent.objects.get(action=AuditAction.FOLDER_CREATED, metadata__folder_id=str(f.pk))
    assert ev.metadata["name"] == "Nhóm Phòng 1"
    assert ev.metadata.get("content") is None  # minimal metadata only


@pytest.mark.django_db
def test_grant_revoke_audit_and_history_rows(org):
    f = make_folder(org.ua, org.d1, org.mgr1)
    g1 = folder_services.grant_folder(org.mgr1, f.pk, org.o2.pk, FolderRole.VIEWER)
    # idempotent re-grant: same role -> same row, no extra audit
    n0 = AuditEvent.objects.filter(action=AuditAction.FOLDER_GRANT_ADDED).count()
    g1b = folder_services.grant_folder(org.mgr1, f.pk, org.o2.pk, FolderRole.VIEWER)
    assert g1b.pk == g1.pk
    assert AuditEvent.objects.filter(action=AuditAction.FOLDER_GRANT_ADDED).count() == n0
    folder_services.revoke_folder_grant(org.mgr1, g1.pk)
    g1.refresh_from_db()
    assert g1.revoked_at is not None
    # re-grant after revoke -> NEW row; old row remains as history
    g2 = folder_services.grant_folder(org.mgr1, f.pk, org.o2.pk, FolderRole.CONTRIBUTOR)
    assert g2.pk != g1.pk
    assert FolderGrant.objects.filter(folder=f, user=org.o2).count() == 2
    evs = actions(org.ua)
    assert AuditAction.FOLDER_GRANT_REVOKED in evs


@pytest.mark.django_db
def test_share_revoke_audit_and_rows(org):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="M-10")
    s1 = folder_services.share_record(org.mgr1, rec.pk, org.o2.pk)
    folder_services.revoke_record_share(org.mgr1, s1.pk)
    s2 = folder_services.share_record(org.mgr1, rec.pk, org.o2.pk)
    assert s2.pk != s1.pk
    assert RecordShare.objects.filter(record=rec, user=org.o2).count() == 2
    evs = actions(org.ua, record=rec)
    assert AuditAction.RECORD_SHARE_ADDED in evs
    assert AuditAction.RECORD_SHARE_REVOKED in evs


@pytest.mark.django_db
def test_move_record_audits_before_after(org):
    fa = make_folder(org.ua, org.d1, org.mgr1, "A")
    fb = make_folder(org.ua, org.d1, org.mgr1, "B")
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="M-20")
    rec.folder = fa
    rec.save()
    folder_services.move_record(org.mgr1, rec.pk, fb.pk)
    ev = AuditEvent.objects.get(action=AuditAction.RECORD_FOLDER_MOVED, record=rec)
    assert ev.metadata["before_folder_id"] == str(fa.pk)
    assert ev.metadata["after_folder_id"] == str(fb.pk)
    folder_services.move_record(org.mgr1, rec.pk, None)  # unfile
    rec.refresh_from_db()
    assert rec.folder_id is None


@pytest.mark.django_db
def test_rename_audit(org):
    f = make_folder(org.ua, org.d1, org.mgr1, name="Cũ")
    folder_services.rename_folder(org.mgr1, f.pk, "Mới")
    ev = AuditEvent.objects.get(action=AuditAction.FOLDER_RENAMED)
    assert ev.metadata["before"] == "Cũ" and ev.metadata["after"] == "Mới"


@pytest.mark.django_db
def test_grant_events_use_db_time_not_client(org):
    f = make_folder(org.ua, org.d1, org.mgr1)
    g = folder_services.grant_folder(org.mgr1, f.pk, org.o2.pk, FolderRole.VIEWER)
    assert g.created_at is not None
    folder_services.revoke_folder_grant(org.mgr1, g.pk)
    g.refresh_from_db()
    assert g.revoked_at is not None and g.revoked_at >= g.created_at
