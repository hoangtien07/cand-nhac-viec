"""Single source of truth for record authorization (ARCHITECTURE §4, CONTEXT §D). Deny by default.

Every list/detail/report/notification query and every mutation goes through these functions.
Callers must re-check mutations under the record row lock (services do this).
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q

from apps.accounts.models import Role
from apps.organization.models import Department

from .models import RecordAssignee, RecordStatus, RecordWatcher, WorkRecord


def _business(user):
    return bool(getattr(user, "is_authenticated", False) and user.is_business_user)


def managed_department_ids(user):
    if not _business(user) or user.role != Role.DEPT_MANAGER:
        return set()
    return set(
        Department.objects.filter(manager=user, unit_id=user.unit_id, is_active=True).values_list(
            "id", flat=True
        )
    )


def _active_assignee(user):
    return RecordAssignee.objects.filter(record=OuterRef("pk"), user=user, is_active=True)


def _active_watcher(user):
    return RecordWatcher.objects.filter(record=OuterRef("pk"), user=user, is_active=True)


def _participant_q(user):
    return Q(created_by=user) | Q(assigner=user) | Q(Exists(_active_assignee(user)))


def _managed_q(dept_ids):
    managed_assignee = RecordAssignee.objects.filter(
        record=OuterRef("pk"), is_active=True, user__department_id__in=dept_ids
    )
    return Q(owner_department_id__in=dept_ids) | Q(Exists(managed_assignee))


def visible_records_queryset(user):
    if not _business(user):
        return WorkRecord.objects.none()
    qs = WorkRecord.objects.filter(unit_id=user.unit_id)
    if user.role == Role.LEADER:
        return qs
    q = _participant_q(user) | Q(Exists(_active_watcher(user)))
    dept_ids = managed_department_ids(user)
    if dept_ids:
        q |= _managed_q(dept_ids)
    return qs.filter(q)


def report_records_queryset(user):
    """Report scope: leader=unit, manager=managed scope + own participation, officer=own participation.
    Watch-only records are excluded from reports (matrix: watcher 'Xem báo cáo: Không mặc định')."""
    if not _business(user):
        return WorkRecord.objects.none()
    qs = WorkRecord.objects.filter(unit_id=user.unit_id)
    if user.role == Role.LEADER:
        return qs
    q = _participant_q(user)
    dept_ids = managed_department_ids(user)
    if dept_ids:
        q |= _managed_q(dept_ids)
    return qs.filter(q)


def can_view_reports(user):
    return _business(user)


def can_view_record(user, record):
    return visible_records_queryset(user).filter(pk=record.pk).exists()


def creatable_departments(user):
    if not _business(user):
        return Department.objects.none()
    qs = Department.objects.filter(unit_id=user.unit_id, is_active=True)
    if user.role == Role.LEADER:
        return qs
    if user.role == Role.DEPT_MANAGER:
        return qs.filter(id__in=managed_department_ids(user))
    if user.department_id:
        return qs.filter(id=user.department_id)
    return qs.none()


def can_create_record(user, owner_department):
    return creatable_departments(user).filter(pk=owner_department.pk).exists()


def assignable_users(user, owner_department):
    """Who `user` may assign on a record of `owner_department` (H01: officers stay in own dept)."""
    from apps.accounts.models import User

    if not _business(user):
        return User.objects.none()
    qs = User.objects.filter(
        unit_id=user.unit_id,
        is_active=True,
        role__in=[Role.LEADER, Role.DEPT_MANAGER, Role.OFFICER],
        department__is_active=True,
    )
    if user.role == Role.LEADER:
        return qs
    if user.role == Role.DEPT_MANAGER:
        return qs.filter(department_id__in=managed_department_ids(user))
    return qs.filter(department_id=user.department_id) if user.department_id else qs.none()


def watchable_users(user):
    """H08: watchers may come from any department in the same unit; business users only."""
    from apps.accounts.models import User

    if not _business(user):
        return User.objects.none()
    return User.objects.filter(
        unit_id=user.unit_id, is_active=True, role__in=[Role.LEADER, Role.DEPT_MANAGER, Role.OFFICER]
    )


def _manages_record(user, record):
    if not _business(user) or record.unit_id != user.unit_id:
        return False
    if user.role == Role.LEADER:
        return True
    if user.role == Role.DEPT_MANAGER:
        return record.owner_department_id in managed_department_ids(user)
    return (record.created_by_id == user.pk or record.assigner_id == user.pk) and (
        record.owner_department_id == user.department_id
    )


def can_manage_assignment(user, record):
    return record.status == RecordStatus.OPEN and _manages_record(user, record)


def can_edit_deadline(user, record):
    return record.status == RecordStatus.OPEN and _manages_record(user, record)


def can_manage_watchers(user, record):
    return record.status == RecordStatus.OPEN and _manages_record(user, record)


def can_submit_result(user, record):
    """Only an active assignee may submit; leader/manager roles add nothing (ARCHITECTURE §4)."""
    if not _business(user) or record.unit_id != user.unit_id:
        return False
    return RecordAssignee.objects.filter(record=record, user=user, is_active=True).exists()


def can_view_audit(user, record):
    return can_view_record(user, record)


def require(allowed, message="Bạn không có quyền thực hiện thao tác này."):
    if not allowed:
        raise PermissionDenied(message)
