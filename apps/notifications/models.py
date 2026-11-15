import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now


class NotificationType(models.TextChoices):
    DUE_SOON = "DUE_SOON", "Sắp đến hạn"
    DUE_TODAY = "DUE_TODAY", "Đến hạn hôm nay"
    OVERDUE = "OVERDUE", "Quá hạn"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("organization.Unit", on_delete=models.PROTECT, related_name="+")
    record = models.ForeignKey("records.WorkRecord", on_delete=models.PROTECT, related_name="notifications")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notifications"
    )
    type = models.CharField(max_length=20, choices=NotificationType.choices)
    reminder_bucket = models.DateField()
    dedupe_key = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    read_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "resolved_at", "read_at"])]

    @staticmethod
    def make_dedupe_key(record_id, ntype, bucket, recipient_id):
        return f"{record_id}:{ntype}:{bucket.isoformat()}:{recipient_id}"

    @property
    def is_pending(self):
        return self.resolved_at is None
