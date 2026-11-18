"""Scoped read queries for KPI screens (PLAN §5.3, WP6/WP7). Never returns score data
of other users/subjects to unauthorized viewers — the queryset is the boundary."""

from .capabilities import KpiCapability
from .models import (
    EvaluationStatus,
    GrantScope,
    KpiCapabilityGrant,
    KpiEvaluation,
    KpiReminderEvent,
    KpiScoreCorrection,
    PolicyVersionStatus,
)
from .policies import kpi_enabled

_SCORE_VIEW_CAPS = (
    KpiCapability.EVALUATE,
    KpiCapability.SCORE_FINALIZE,
    KpiCapability.SCORE_CORRECT,
    KpiCapability.REMINDER_ISSUE,
    KpiCapability.VIEW_UNIT,
)


def _dept_scope(user, capabilities):
    """None = whole unit; set() = department ids the user's DEPARTMENT grants cover."""
    grants = KpiCapabilityGrant.objects.filter(
        unit_id=user.unit_id, user=user, capability__in=capabilities, revoked_at__isnull=True
    )
    if grants.filter(scope=GrantScope.UNIT).exists():
        return None
    return set(
        grants.filter(scope=GrantScope.DEPARTMENT).values_list("department_id", flat=True)
    )


def eval_status_map(record_ids):
    """record_id -> 'NONE'|'DRAFT'|'FINALIZED' aggregated over subjects (no score data)."""
    rows = (
        KpiEvaluation.objects.filter(record_id__in=record_ids)
        .values_list("record_id", "status")
    )
    seen = {}
    for rid, status in rows:
        seen.setdefault(rid, []).append(status)
    out = {}
    for rid, statuses in seen.items():
        out[rid] = "FINALIZED" if all(s == EvaluationStatus.FINALIZED for s in statuses) else "DRAFT"
    return out


def own_score_map(user, record_ids):
    """Only the viewer's own FINALIZED scores -> {record_id: (evaluation_id, final_score)}."""
    superseded = KpiScoreCorrection.objects.filter(
        evaluation__subject_user=user, evaluation__record_id__in=record_ids
    ).values_list("supersedes_snapshot_id", flat=True)
    snaps = (
        KpiEvaluation.objects.filter(
            subject_user=user, record_id__in=record_ids, status=EvaluationStatus.FINALIZED
        )
        .exclude(snapshots__pk__in=superseded)
        .exclude(snapshots__isnull=True)
        .values_list("record_id", "pk", "snapshots__final_score")
    )
    # latest revision per record
    out = {}
    for rid, eid, score in snaps:
        out[rid] = (eid, score)
    return out


def my_finalized_evaluations(user):
    superseded = KpiScoreCorrection.objects.filter(
        evaluation__subject_user=user
    ).values_list("supersedes_snapshot_id", flat=True)
    qs = (
        KpiEvaluation.objects.filter(subject_user=user, status=EvaluationStatus.FINALIZED)
        .select_related("record", "policy_version")
        .order_by("-finalized_at")
    )
    rows = []
    for ev in qs:
        snap = ev.snapshots.exclude(pk__in=superseded).order_by("-revision").first()
        if snap:
            rows.append((ev, snap))
    return rows


def can_view_scores(user):
    """Any active grant (UNIT or DEPARTMENT) in the score-view capability set."""
    if not (kpi_enabled() and getattr(user, "is_business_user", False)):
        return False
    return KpiCapabilityGrant.objects.filter(
        unit_id=user.unit_id, user=user,
        capability__in=_SCORE_VIEW_CAPS, revoked_at__isnull=True,
    ).exists()


def scoped_evaluations(user):
    """Evaluations a score-viewer may list (unit grant = all; dept grants = those depts)."""
    if not can_view_scores(user):
        return KpiEvaluation.objects.none()
    qs = KpiEvaluation.objects.filter(unit_id=user.unit_id).select_related(
        "record", "subject_user", "subject_user__department", "policy_version", "policy_version__family"
    )
    dept_scope = _dept_scope(user, _SCORE_VIEW_CAPS)
    if dept_scope is not None:
        qs = qs.filter(record__owner_department_id__in=dept_scope)
    return qs


def attach_effective_snapshots(evaluations):
    """{evaluation_id: effective snapshot} resolved via corrections, not a mutable flag."""
    ids = [e.pk for e in evaluations]
    superseded = set(
        KpiScoreCorrection.objects.filter(evaluation_id__in=ids).values_list(
            "supersedes_snapshot_id", flat=True
        )
    )
    out = {}
    for ev in evaluations:
        snap = ev.snapshots.exclude(pk__in=superseded).order_by("-revision").first()
        out[ev.pk] = snap
    return out


def scoped_reminders(user):
    if not kpi_enabled() or not user.is_business_user:
        return KpiReminderEvent.objects.none()
    if not KpiCapabilityGrant.objects.filter(
        unit_id=user.unit_id, user=user,
        capability=KpiCapability.REMINDER_ISSUE, revoked_at__isnull=True,
    ).exists():
        return KpiReminderEvent.objects.none()
    qs = KpiReminderEvent.objects.filter(unit_id=user.unit_id).select_related(
        "record", "subject_user", "actor", "revocation"
    )
    dept_scope = _dept_scope(user, (KpiCapability.REMINDER_ISSUE,))
    if dept_scope is not None:
        qs = qs.filter(record__owner_department_id__in=dept_scope)
    return qs


def active_versions(user):
    """ACTIVE policy versions of the user's unit (for reference on score pages)."""
    if not user.unit_id:
        return []
    from .models import KpiPolicyVersion

    return list(
        KpiPolicyVersion.objects.filter(
            family__unit_id=user.unit_id, status=PolicyVersionStatus.ACTIVE
        ).select_related("family")
    )
