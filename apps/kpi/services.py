"""KPI config lifecycle: DRAFT CRUD → validate → publish under family row lock (PLAN §5.1, WP4).

Every mutation re-checks capability grants inside the transaction. Published versions
are immutable — edits require a new DRAFT version.
"""

import hashlib
import json
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import audit_append
from apps.records.timeutils import db_now

from . import policies
from .models import (
    KpiCapabilityGrant,
    KpiCriterion,
    KpiPenaltyBand,
    KpiPolicyFamily,
    KpiPolicyVersion,
    PenaltyBandKind,
    PolicyVersionStatus,
)


def _audit(action, *, unit, actor, **meta):
    audit_append(action, unit=unit, actor=actor, **meta)


def _version_in_unit(user, version_id):
    """404-style deny for cross-unit / unknown ids (PLAN §7.2)."""
    try:
        return KpiPolicyVersion.objects.select_related("family").get(
            pk=version_id, family__unit_id=user.unit_id
        )
    except KpiPolicyVersion.DoesNotExist:
        raise KpiPolicyVersion.DoesNotExist("Không tìm thấy phiên bản cấu hình.") from None


def visible_versions(user):
    if not policies.can_view_kpi_config(user):
        return KpiPolicyVersion.objects.none()
    return KpiPolicyVersion.objects.filter(family__unit_id=user.unit_id).select_related("family")


@transaction.atomic
def create_draft(actor, *, task_kind, name, max_points, combination_strategy, clone_from_id=None):
    policies.require(policies.can_configure_kpi(actor))
    family, created = KpiPolicyFamily.objects.get_or_create(
        unit_id=actor.unit_id, task_kind=task_kind,
        defaults={"name": name.strip()[:200], "created_by": actor},
    )
    if not created and name.strip():
        family.name = name.strip()[:200]
        family.save(update_fields=["name"])
    next_no = (family.versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    version = KpiPolicyVersion.objects.create(
        family=family, version=next_no, max_points=max_points,
        combination_strategy=combination_strategy, created_by=actor,
    )
    if clone_from_id:
        src = _version_in_unit(actor, clone_from_id)
        if src.family_id != family.pk:
            raise ValidationError("Chỉ sao chép từ phiên bản cùng loại nhiệm vụ.")
        KpiCriterion.objects.bulk_create(
            [
                KpiCriterion(
                    version=version, code=c.code, title=c.title,
                    description_short=c.description_short, weight_percent=c.weight_percent,
                    position=c.position, required=c.required,
                )
                for c in src.criteria.all()
            ]
        )
        KpiPenaltyBand.objects.bulk_create(
            [
                KpiPenaltyBand(
                    version=version, kind=b.kind, min_value=b.min_value,
                    max_value=b.max_value, deduction_percent=b.deduction_percent,
                )
                for b in src.penalty_bands.all()
            ]
        )
    _audit(AuditAction.KPI_CONFIG_CREATED, unit=actor.unit, actor=actor,
           version=str(version.pk), family=str(family.pk), task_kind=task_kind)
    return version


def _locked_draft(actor, version_id):
    version = _version_in_unit(actor, version_id)
    policies.require(policies.can_configure_kpi(actor))
    if version.status != PolicyVersionStatus.DRAFT:
        raise ValidationError("Chỉ chỉnh sửa được phiên bản nháp (DRAFT).")
    return version


@transaction.atomic
def update_draft(actor, version_id, *, max_points, combination_strategy):
    version = _locked_draft(actor, version_id)
    version.max_points = max_points
    version.combination_strategy = combination_strategy
    version.save(update_fields=["max_points", "combination_strategy"])
    _audit(AuditAction.KPI_CONFIG_UPDATED, unit=actor.unit, actor=actor, version=str(version.pk))
    return version


@transaction.atomic
def replace_criteria(actor, version_id, rows):
    """rows: [{code,title,description_short,weight_percent,position,required}]."""
    version = _locked_draft(actor, version_id)
    version.criteria.all().delete()
    KpiCriterion.objects.bulk_create([KpiCriterion(version=version, **r) for r in rows])
    _audit(AuditAction.KPI_CONFIG_UPDATED, unit=actor.unit, actor=actor,
           version=str(version.pk), criteria=len(rows))


@transaction.atomic
def replace_penalty_bands(actor, version_id, rows):
    """rows: [{kind,min_value,max_value,deduction_percent}]."""
    version = _locked_draft(actor, version_id)
    version.penalty_bands.all().delete()
    KpiPenaltyBand.objects.bulk_create([KpiPenaltyBand(version=version, **r) for r in rows])
    _audit(AuditAction.KPI_CONFIG_UPDATED, unit=actor.unit, actor=actor,
           version=str(version.pk), bands=len(rows))


def _band_errors(kind, bands):
    """Bands must tile [0, +∞) without gaps/overlaps (PLAN §6.2, §6.3.2)."""
    errors = []
    if not bands:
        return [f"Chưa có dải trừ cho «{PenaltyBandKind(kind).label}»."]
    bands = sorted(bands, key=lambda b: b.min_value)
    if bands[0].min_value != 0:
        errors.append(f"Dải «{PenaltyBandKind(kind).label}» phải bắt đầu từ 0.")
    for i, band in enumerate(bands):
        if band.max_value is None and i != len(bands) - 1:
            errors.append(f"Chỉ dải cuối của «{PenaltyBandKind(kind).label}» được để mở (không max).")
        if band.max_value is not None and band.max_value < band.min_value:
            errors.append(f"Dải {band.min_value}–{band.max_value}: max nhỏ hơn min.")
        if i + 1 < len(bands) and band.max_value is not None and bands[i + 1].min_value != band.max_value + 1:
            errors.append(
                f"Dải «{PenaltyBandKind(kind).label}» bị chồng/hở quanh giá trị {band.max_value}."
            )
    if bands[-1].max_value is not None:
        errors.append(f"Dải cuối của «{PenaltyBandKind(kind).label}» phải để mở (không max).")
    return errors


def validate_version(version):
    """Return list of validation errors; empty = publishable."""
    errors = []
    criteria = list(version.criteria.all())
    if not criteria:
        errors.append("Chưa có tiêu chí chấm điểm.")
    total = sum((c.weight_percent for c in criteria), Decimal("0"))
    if criteria and total != Decimal("100"):
        errors.append(f"Tổng trọng số phải bằng 100 (đang là {total}).")
    for kind, _label in PenaltyBandKind.choices:
        errors += _band_errors(kind, list(version.penalty_bands.filter(kind=kind)))
    return errors


def fingerprint(version):
    """sha256 over canonical config content — stored at publish, re-checked then."""
    payload = {
        "version": version.version,
        "max_points": str(version.max_points),
        "strategy": version.combination_strategy,
        "criteria": [
            [c.code, c.title, str(c.weight_percent), c.position, c.required]
            for c in version.criteria.order_by("position", "code")
        ],
        "bands": [
            [b.kind, b.min_value, b.max_value, str(b.deduction_percent)]
            for b in version.penalty_bands.order_by("kind", "min_value")
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def publish_version(actor, version_id, reason=""):
    """Activate a DRAFT under family row lock; supersede the previous ACTIVE (PLAN §5.1)."""
    if not reason.strip():
        raise ValidationError("Cần nhập lý do xác nhận khi kích hoạt.")
    version = _version_in_unit(actor, version_id)
    family = KpiPolicyFamily.objects.select_for_update().get(pk=version.family_id)
    version = KpiPolicyVersion.objects.select_for_update().get(pk=version.pk)
    policies.require(policies.can_publish_kpi(actor))
    if version.status != PolicyVersionStatus.DRAFT:
        raise ValidationError("Chỉ kích hoạt được phiên bản DRAFT.")
    errors = validate_version(version)
    if errors:
        raise ValidationError(errors)
    now = db_now()
    previous = family.versions.filter(status=PolicyVersionStatus.ACTIVE).exclude(pk=version.pk)
    for old in previous:
        old.status = PolicyVersionStatus.SUPERSEDED
        old.save(update_fields=["status"])
    version.status = PolicyVersionStatus.ACTIVE
    version.fingerprint = fingerprint(version)
    version.published_by = actor
    version.published_at = now
    version.effective_from = now
    version.save(update_fields=["status", "fingerprint", "published_by", "published_at", "effective_from"])
    family.active_version = version
    family.save(update_fields=["active_version"])
    _audit(
        AuditAction.KPI_CONFIG_PUBLISHED, unit=actor.unit, actor=actor,
        version=str(version.pk), fingerprint=version.fingerprint,
        superseded=[str(v.pk) for v in previous], reason=reason[:200],
    )
    return version


# --- capability grant management (admin flow; returns metadata only, never scores) ---

@transaction.atomic
def grant_capability(actor, *, user, capability, scope, department=None, approved_by=None, reason=""):
    policies.require(policies.can_manage_grants(actor))
    if user.unit_id != actor.unit_id:
        raise PermissionDenied("Chỉ cấp quyền trong cùng đơn vị.")
    if capability != "KPI_GRANT_MANAGE" and user.is_sys_admin:
        raise ValidationError("Không cấp quyền nghiệp vụ KPI cho quản trị kỹ thuật (PLAN §5.2).")
    if scope == "DEPARTMENT":
        if department is None or department.unit_id != actor.unit_id:
            raise ValidationError("Phòng/đội của scope phải thuộc đơn vị.")
    else:
        department = None
    existing = KpiCapabilityGrant.objects.filter(
        unit_id=actor.unit_id, user=user, capability=capability, scope=scope,
        department=department, revoked_at__isnull=True,
    ).first()
    if existing:
        return existing
    grant = KpiCapabilityGrant.objects.create(
        unit_id=actor.unit_id, user=user, capability=capability, scope=scope,
        department=department, granted_by=actor, approved_by=approved_by, reason=reason[:200],
    )
    _audit(AuditAction.KPI_PERMISSION_GRANTED, unit=actor.unit, actor=actor,
           target_user=str(user.pk), capability=capability, scope=scope)
    return grant


@transaction.atomic
def revoke_capability(actor, grant_id):
    grant = KpiCapabilityGrant.objects.select_for_update().get(pk=grant_id, unit_id=actor.unit_id)
    policies.require(policies.can_manage_grants(actor))
    if grant.revoked_at is not None:
        return grant
    grant.revoked_at = db_now()
    grant.save(update_fields=["revoked_at"])
    _audit(AuditAction.KPI_PERMISSION_REVOKED, unit=actor.unit, actor=actor,
           target_user=str(grant.user_id), capability=grant.capability)
    return grant
