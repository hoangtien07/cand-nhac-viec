"""Folder/share mutations: single transaction, row locks, audit, idempotent (DECISIONS §5)."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from apps.audit.models import AuditAction
from apps.audit.services import audit_append
from apps.records import policies as record_policies
from apps.records.models import RecordShare, ShareAccess, WorkRecord

from . import folder_policies as policies
from .models import FolderGrant, FolderRole, WorkFolder

User = get_user_model()


def _grantee_or_error(actor, user_id):
    user = User.objects.filter(pk=user_id).select_related("department").first()
    if user is None or user.unit_id != actor.unit_id or not user.is_business_user:
        raise ValidationError("Người được cấp quyền phải là người dùng nghiệp vụ cùng đơn vị.")
    return user


@transaction.atomic
def create_folder(actor, *, name, owner_department, description_short=""):
    record_policies.require(
        policies.can_create_folder(actor, owner_department),
        "Bạn không có quyền tạo nhóm hồ sơ cho phòng/đội này.",
    )
    folder = WorkFolder(
        unit_id=actor.unit_id,
        owner_department=owner_department,
        name=(name or "").strip(),
        description_short=(description_short or "").strip(),
        created_by=actor,
    )
    try:
        folder.full_clean(exclude=["name_normalized"])
        folder.save()
    except IntegrityError as e:
        raise ValidationError("Đã tồn tại nhóm hồ sơ cùng tên trong phòng/đội này.") from e
    # The creator receives an explicit MANAGER grant so folder administration never depends
    # on an implicit path (decision recorded in ADR-002).
    FolderGrant.objects.create(folder=folder, user=actor, role=FolderRole.MANAGER, granted_by=actor)
    audit_append(
        AuditAction.FOLDER_CREATED,
        unit=folder.unit_id,
        actor=actor,
        folder_id=str(folder.pk),
        name=folder.name,
        owner_department=str(folder.owner_department_id),
    )
    folder.refresh_from_db()
    return folder


@transaction.atomic
def rename_folder(actor, folder_id, name):
    folder = _locked_folder(actor, folder_id)
    record_policies.require(policies.can_manage_folder(actor, folder))
    new_name = (name or "").strip()
    if not new_name:
        raise ValidationError("Tên nhóm hồ sơ không được để trống.")
    if new_name == folder.name:
        return folder
    before = folder.name
    try:
        folder.name = new_name
        folder.save(update_fields=["name", "name_normalized"])
        WorkFolder.objects.filter(pk=folder.pk).update(updated_at=Now())
    except IntegrityError as e:
        raise ValidationError("Đã tồn tại nhóm hồ sơ cùng tên trong phòng/đội này.") from e
    audit_append(
        AuditAction.FOLDER_RENAMED,
        unit=folder.unit_id,
        actor=actor,
        folder_id=str(folder.pk),
        before=before,
        after=new_name,
    )
    return folder


def _locked_folder(actor, folder_id):
    folder = (
        WorkFolder.objects.select_for_update().select_related("owner_department").filter(pk=folder_id).first()
    )
    if folder is None or not policies.can_view_folder(actor, folder):
        raise WorkFolder.DoesNotExist
    return folder


@transaction.atomic
def grant_folder(actor, folder_id, user_id, role):
    folder = _locked_folder(actor, folder_id)
    record_policies.require(
        policies.can_manage_folder_grants(actor, folder),
        "Bạn không có quyền quản lý thành viên nhóm hồ sơ này.",
    )
    if role not in FolderRole.values:
        raise ValidationError("Vai trò nhóm không hợp lệ.")
    user = _grantee_or_error(actor, user_id)
    current = (
        FolderGrant.objects.select_for_update()
        .filter(folder=folder, user=user, revoked_at__isnull=True)
        .first()
    )
    if current:
        if current.role == role:
            return current  # idempotent re-grant
        current.role = role
        current.save(update_fields=["role"])
        audit_append(
            AuditAction.FOLDER_GRANT_ADDED,
            unit=folder.unit_id,
            actor=actor,
            folder_id=str(folder.pk),
            user_id=str(user.pk),
            role=role,
        )
        return current
    # A revoked grant stays as a historical row; re-granting creates a NEW row.
    try:
        with transaction.atomic():
            grant = FolderGrant.objects.create(folder=folder, user=user, role=role, granted_by=actor)
    except IntegrityError:
        return FolderGrant.objects.get(folder=folder, user=user, revoked_at__isnull=True)
    audit_append(
        AuditAction.FOLDER_GRANT_ADDED,
        unit=folder.unit_id,
        actor=actor,
        folder_id=str(folder.pk),
        user_id=str(user.pk),
        role=role,
    )
    return grant


@transaction.atomic
def revoke_folder_grant(actor, grant_id):
    grant = (
        FolderGrant.objects.select_for_update().select_related("folder", "user").filter(pk=grant_id).first()
    )
    if grant is None:
        raise FolderGrant.DoesNotExist
    folder = WorkFolder.objects.select_for_update().get(pk=grant.folder_id)
    # Archived folders still allow grant cleanup (deny-by-default direction).
    if folder.unit_id != actor.unit_id or not policies.can_manage_folder_grants(
        actor, folder, include_archived=True
    ):
        raise WorkFolder.DoesNotExist
    if grant.is_active:
        grant.revoke()
        audit_append(
            AuditAction.FOLDER_GRANT_REVOKED,
            unit=folder.unit_id,
            actor=actor,
            folder_id=str(folder.pk),
            user_id=str(grant.user_id),
            role=grant.role,
        )
    return grant


@transaction.atomic
def share_record(actor, record_id, user_id):
    record = WorkRecord.objects.select_for_update().filter(pk=record_id).first()
    if record is None or not record_policies.can_view_record(actor, record):
        raise WorkRecord.DoesNotExist
    record_policies.require(
        record_policies.can_share_record(actor, record),
        "Bạn không có quyền chia sẻ hồ sơ này.",
    )
    user = _grantee_or_error(actor, user_id)
    if user.unit_id != record.unit_id:
        raise ValidationError("Người được chia sẻ phải thuộc cùng đơn vị với hồ sơ.")
    if RecordShare.objects.filter(record=record, user=user, revoked_at__isnull=True).exists():
        return RecordShare.objects.get(record=record, user=user, revoked_at__isnull=True)
    # A revoked share stays as a historical row; re-sharing creates a NEW row.
    try:
        with transaction.atomic():
            share = RecordShare.objects.create(
                record=record, user=user, access=ShareAccess.VIEWER, granted_by=actor
            )
    except IntegrityError:
        return RecordShare.objects.get(record=record, user=user, revoked_at__isnull=True)
    audit_append(
        AuditAction.RECORD_SHARE_ADDED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        reference_no=record.reference_no,
        user_id=str(user.pk),
        access=ShareAccess.VIEWER,
    )
    return share


@transaction.atomic
def revoke_record_share(actor, share_id):
    share = (
        RecordShare.objects.select_for_update().select_related("record", "user").filter(pk=share_id).first()
    )
    if share is None:
        raise RecordShare.DoesNotExist
    record = WorkRecord.objects.select_for_update().get(pk=share.record_id)
    if not record_policies.can_view_record(actor, record):
        raise WorkRecord.DoesNotExist
    record_policies.require(record_policies.can_share_record(actor, record))
    if share.is_active:
        share.revoke()
        audit_append(
            AuditAction.RECORD_SHARE_REVOKED,
            unit=record.unit_id,
            actor=actor,
            record=record,
            reference_no=record.reference_no,
            user_id=str(share.user_id),
        )
    return share


@transaction.atomic
def move_record(actor, record_id, folder_id):
    """Move under the record row lock; re-checks record authority AND destination folder (§5.5)."""
    record = WorkRecord.objects.select_for_update().filter(pk=record_id).first()
    if record is None or not record_policies.can_view_record(actor, record):
        raise WorkRecord.DoesNotExist
    folder = None
    if folder_id is not None:
        folder = WorkFolder.objects.select_for_update().filter(pk=folder_id, is_archived=False).first()
        if folder is None:
            raise WorkFolder.DoesNotExist
    record_policies.require(
        policies.can_move_record(actor, record, folder),
        "Bạn không có quyền chuyển hồ sơ sang nhóm này.",
    )
    before = record.folder_id
    if before == (folder.pk if folder else None):
        return record
    WorkRecord.objects.filter(pk=record.pk).update(folder=folder, updated_at=Now())
    record.refresh_from_db()
    audit_append(
        AuditAction.RECORD_FOLDER_MOVED,
        unit=record.unit_id,
        actor=actor,
        record=record,
        reference_no=record.reference_no,
        before_folder_id=str(before) if before else None,
        after_folder_id=str(folder.pk) if folder else None,
    )
    return record
