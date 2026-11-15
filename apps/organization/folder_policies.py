"""Centralized folder authorization (DECISIONS §3/§4, ADR-002). Deny by default, same-unit only.

Folder grants add READ visibility to records; they never grant submit/edit/report rights.
Archived folders are suspended: they disappear from browsing AND stop conferring derived access.
"""

from django.db.models import Exists, OuterRef, Q

from apps.accounts.models import BUSINESS_ROLES, Role
from apps.records import policies as record_policies

from .models import FolderGrant, FolderRole, WorkFolder

# Re-exported so `apps.organization.folder_policies` is the single import surface (DECISIONS §4).
can_share_record = record_policies.can_share_record
shareable_users = record_policies.shareable_users


def _business(user):
    return bool(getattr(user, "is_authenticated", False) and user.is_business_user)


def _active_grant(user, folder, roles=None):
    qs = FolderGrant.objects.filter(folder=folder, user=user, revoked_at__isnull=True)
    if roles is not None:
        qs = qs.filter(role__in=roles)
    return qs.exists()


def visible_folders_queryset(user):
    """Same-unit, non-archived folders the user may browse: leader sees all; owner-dept
    manager sees its department folders; everyone else needs an active grant."""
    if not _business(user):
        return WorkFolder.objects.none()
    qs = WorkFolder.objects.filter(unit_id=user.unit_id, is_archived=False)
    if user.role == Role.LEADER:
        return qs
    q = Q(Exists(FolderGrant.objects.filter(folder=OuterRef("pk"), user=user, revoked_at__isnull=True)))
    dept_ids = record_policies.managed_department_ids(user)
    if dept_ids:
        q |= Q(owner_department_id__in=dept_ids)
    return qs.filter(q)


def can_view_folder(user, folder):
    if not _business(user) or folder.unit_id != user.unit_id or folder.is_archived:
        return False
    if user.role == Role.LEADER:
        return True
    if folder.owner_department_id in record_policies.managed_department_ids(user):
        return True
    return _active_grant(user, folder)


def _is_owner_dept_manager(user, folder):
    return (
        user.role == Role.DEPT_MANAGER
        and folder.owner_department_id in record_policies.managed_department_ids(user)
    )


def can_manage_folder(user, folder, include_archived=False):
    """Leader, owner-department manager, or active MANAGER grant (§3 matrix).

    include_archived=True is only for grant revocation/cleanup on suspended folders —
    never for browsing or content access."""
    if not _business(user) or folder.unit_id != user.unit_id:
        return False
    if folder.is_archived and not include_archived:
        return False
    if user.role == Role.LEADER or _is_owner_dept_manager(user, folder):
        return True
    return _active_grant(user, folder, [FolderRole.MANAGER])


def can_manage_folder_grants(user, folder, include_archived=False):
    return can_manage_folder(user, folder, include_archived=include_archived)


def can_create_folder(user, owner_department):
    """Same scope as creating a record for that department (leader/its manager/own dept)."""
    return record_policies.can_create_record(user, owner_department)


def can_create_record_in_folder(user, folder):
    """ASSUMPTION-F3 (ADR-002): folder membership alone never grants record creation — the
    organization's existing create policy for the owner department must still allow it."""
    return can_view_folder(user, folder) and record_policies.can_create_record(user, folder.owner_department)


def can_move_record(user, record, folder):
    """Move = authority on the record AND manage-rights on the destination folder, plus the
    v1 invariant folder.owner_department == record.owner_department."""
    if not _business(user) or record.unit_id != user.unit_id:
        return False
    if folder is not None and (
        folder.unit_id != user.unit_id or folder.owner_department_id != record.owner_department_id
    ):
        return False
    if not record_policies.manages_record(user, record):
        return False
    return folder is None or can_manage_folder(user, folder)


def movable_folders(user, record):
    """Destination-folder candidates for a move: same owner department + manage rights."""
    if not _business(user) or record.unit_id != user.unit_id:
        return WorkFolder.objects.none()
    qs = WorkFolder.objects.filter(
        unit_id=user.unit_id, owner_department_id=record.owner_department_id, is_archived=False
    )
    if user.role == Role.LEADER:
        return qs
    q = Q(
        Exists(
            FolderGrant.objects.filter(
                folder=OuterRef("pk"), user=user, revoked_at__isnull=True, role=FolderRole.MANAGER
            )
        )
    )
    dept_ids = record_policies.managed_department_ids(user)
    if dept_ids:
        q |= Q(owner_department_id__in=dept_ids)
    return qs.filter(q)


def grantable_users(user, folder):
    """Picker candidates: active same-unit business users without an active grant already."""
    from apps.accounts.models import User

    if not can_manage_folder_grants(user, folder):
        return User.objects.none()
    return User.objects.filter(unit_id=user.unit_id, is_active=True, role__in=BUSINESS_ROLES).exclude(
        pk__in=FolderGrant.objects.filter(folder=folder, revoked_at__isnull=True).values("user_id")
    )
