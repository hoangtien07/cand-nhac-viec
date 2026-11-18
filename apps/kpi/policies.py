"""KPI authorization (PLAN §5.2–§5.3). Deny by default; re-checked on every request.

Rules:
- Grants come only from KpiCapabilityGrant (never is_staff/is_superuser/shares/watchers).
- SYS_ADMIN is denied every business capability even if granted; only KPI_GRANT_MANAGE
  may be held (for the admin grant-management flow) — it never returns score data.
- KPI_VIEW_UNIT additionally requires role LEADER and scope UNIT (PLAN §5.3).
- unit_id always derives from request.user; cross-unit grants are rejected at creation
  in services and filtered out here anyway.
- KPI_ENABLED off ⇒ every business check fails (flag is not a permission bypass).
"""

from django.conf import settings
from django.db.models import Q

from apps.accounts.models import Role

from .capabilities import KpiCapability
from .models import GrantScope, KpiCapabilityGrant

_DENY = "Bạn không có quyền thao tác phân hệ KPI."


def kpi_enabled():
    return bool(getattr(settings, "KPI_ENABLED", False))


def active_grants(user, capability=None):
    """Active grants for the user's own unit (never trusts client-supplied unit_id)."""
    if not getattr(user, "is_authenticated", False) or not user.is_active or not user.unit_id:
        return KpiCapabilityGrant.objects.none()
    qs = KpiCapabilityGrant.objects.filter(unit_id=user.unit_id, user=user, revoked_at__isnull=True)
    return qs.filter(capability=capability) if capability else qs


def _role_allowed(user, capability):
    if capability == KpiCapability.GRANT_MANAGE:
        # Admin grant flow only; returns grant metadata, never score data (PLAN §5.2).
        return user.role in (Role.SYS_ADMIN, Role.LEADER)
    if user.is_sys_admin:  # hard deny — even is_superuser (PLAN §5.3)
        return False
    if capability == KpiCapability.VIEW_UNIT:
        return user.role == Role.LEADER
    return user.role in (Role.LEADER, Role.DEPT_MANAGER)


def has_capability(user, capability, department_id=None):
    """Grant exists, scope covers department_id (None/UNIT-wide op ⇒ UNIT scope only)."""
    if not kpi_enabled() or not _role_allowed(user, capability):
        return False
    grants = active_grants(user, capability)
    if department_id is None:
        return grants.filter(scope=GrantScope.UNIT).exists()
    return grants.filter(
        Q(scope=GrantScope.UNIT) | Q(scope=GrantScope.DEPARTMENT, department_id=department_id)
    ).exists()


def user_departments_scope(user, capability):
    """Department ids the user's DEPARTMENT grants cover (UNIT grants → None = all)."""
    grants = active_grants(user, capability)
    if grants.filter(scope=GrantScope.UNIT).exists():
        return None
    return set(grants.filter(scope=GrantScope.DEPARTMENT).values_list("department_id", flat=True))


def can_view_personal_score(user):
    return kpi_enabled() and getattr(user, "is_business_user", False)


def can_view_scoped_scores(user, department_id=None):
    return has_capability(user, KpiCapability.VIEW_UNIT, department_id)


def can_view_kpi_config(user):
    return has_capability(user, KpiCapability.CONFIG_VIEW) or has_capability(
        user, KpiCapability.CONFIG_EDIT
    )


def can_configure_kpi(user):
    return has_capability(user, KpiCapability.CONFIG_EDIT)


def can_publish_kpi(user):
    return has_capability(user, KpiCapability.CONFIG_PUBLISH)


def can_evaluate(user, department_id=None):
    return has_capability(user, KpiCapability.EVALUATE, department_id)


def can_finalize(user, department_id=None):
    return has_capability(user, KpiCapability.SCORE_FINALIZE, department_id)


def can_issue_kpi_reminder(user, department_id=None):
    return has_capability(user, KpiCapability.REMINDER_ISSUE, department_id)


def can_correct_score(user, department_id=None):
    return has_capability(user, KpiCapability.SCORE_CORRECT, department_id)


def can_manage_grants(user):
    return has_capability(user, KpiCapability.GRANT_MANAGE)


def require(allowed, message=_DENY):
    from django.core.exceptions import PermissionDenied

    if not allowed:
        raise PermissionDenied(message)
