from .models import AuditEvent


def audit_append(action, *, unit, actor=None, record=None, **metadata):
    """Write one audit event. Metadata must stay minimal and non-sensitive (ids, codes, dates)."""
    return AuditEvent.objects.create(
        unit_id=unit.pk if hasattr(unit, "pk") else unit,
        actor=actor,
        record=record,
        action=action,
        metadata=metadata,
    )
