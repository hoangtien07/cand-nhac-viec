import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now


class AuditAction(models.TextChoices):
    RECORD_CREATED = "record.created", "Tạo hồ sơ"
    ASSIGNMENT_CHANGED = "record.assignment_changed", "Đổi người xử lý"
    WATCHERS_CHANGED = "record.watchers_changed", "Đổi người theo dõi"
    DEADLINE_CHANGED = "record.deadline_changed", "Đổi hạn xử lý"
    RESULT_SUBMITTED = "result.submitted", "Nộp số hiệu kết quả"
    RECORD_COMPLETED = "record.completed", "Hồ sơ hoàn thành"
    REMINDER_GENERATED = "reminder.generated", "Tạo nhắc hạn"
    NOTIFICATION_RESOLVED = "notification.resolved", "Nhắc hạn đã giải quyết"
    USER_CREATED = "user.created", "Tạo tài khoản"
    USER_CHANGED = "user.changed", "Sửa tài khoản"
    USER_ROLE_CHANGED = "user.role_changed", "Đổi vai trò"
    DEPARTMENT_CHANGED = "department.changed", "Thay đổi phòng/đội"


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("AuditEvent is append-only")

    def delete(self):
        raise PermissionError("AuditEvent is append-only")


class AuditEvent(models.Model):
    """Append-only at the app layer; a PostgreSQL trigger also rejects UPDATE/DELETE (migration 0002)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="+")
    record = models.ForeignKey(
        "records.WorkRecord", on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=40, choices=AuditAction.choices)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["record", "created_at"]), models.Index(fields=["unit", "action"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("AuditEvent is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("AuditEvent is append-only")
