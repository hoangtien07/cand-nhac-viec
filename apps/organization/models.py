import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


def normalize_folder_name(name):
    return " ".join((name or "").split()).casefold()


class Unit(models.Model):
    """Root data boundary: nothing is ever shown across units."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Tên đơn vị", max_length=200)
    is_active = models.BooleanField("Đang hoạt động", default=True)

    class Meta:
        verbose_name = "Đơn vị"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="departments")
    name = models.CharField("Tên phòng/đội", max_length=200)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Trưởng phòng",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="managed_departments",
    )
    is_active = models.BooleanField("Đang hoạt động", default=True)

    class Meta:
        verbose_name = "Phòng/đội"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["unit", "name"], name="uniq_department_name_per_unit")]

    def __str__(self):
        return self.name


class FolderRole(models.TextChoices):
    MANAGER = "MANAGER", "Quản lý nhóm"
    CONTRIBUTOR = "CONTRIBUTOR", "Cộng tác viên"
    VIEWER = "VIEWER", "Chỉ xem"


class WorkFolder(models.Model):
    """A one-level business collection ("Nhóm hồ sơ"), NOT a staff team (ADR-002).

    Belongs to exactly one Unit and one owner Department. Cross-department access
    only ever comes from explicit same-unit FolderGrant/RecordShare rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="folders")
    owner_department = models.ForeignKey(
        Department,
        verbose_name="Phòng/đội sở hữu",
        on_delete=models.PROTECT,
        related_name="folders",
    )
    name = models.CharField("Tên nhóm hồ sơ", max_length=200)
    name_normalized = models.CharField(max_length=200, editable=False)
    description_short = models.CharField("Mô tả ngắn", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        verbose_name = "Nhóm hồ sơ"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "owner_department", "name_normalized"],
                condition=Q(is_archived=False),
                name="uniq_active_folder_name",
            )
        ]
        indexes = [models.Index(fields=["unit", "is_archived"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name_normalized = normalize_folder_name(self.name)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.owner_department_id and self.unit_id and self.owner_department.unit_id != self.unit_id:
            raise ValidationError({"owner_department": "Phòng/đội sở hữu phải thuộc cùng đơn vị với nhóm."})


class FolderGrant(models.Model):
    """Explicit same-unit folder membership. Soft-revoked via revoked_at; never hard-deleted."""

    folder = models.ForeignKey(WorkFolder, on_delete=models.PROTECT, related_name="grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="folder_grants")
    role = models.CharField(max_length=20, choices=FolderRole.choices, default=FolderRole.VIEWER)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(db_default=Now(), editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["folder", "user"],
                condition=Q(revoked_at__isnull=True),
                name="uniq_active_folder_grant",
            )
        ]
        indexes = [models.Index(fields=["user", "revoked_at"])]

    @property
    def is_active(self):
        return self.revoked_at is None

    def clean(self):
        super().clean()
        if self.folder_id and self.user_id and self.user.unit_id != self.folder.unit_id:
            raise ValidationError({"user": "Thành viên nhóm phải thuộc cùng đơn vị."})

    def revoke(self):
        """Soft revoke using DB time; keeps the row as history (DECISIONS §5)."""
        if self.revoked_at is not None:
            return
        type(self).objects.filter(pk=self.pk, revoked_at__isnull=True).update(revoked_at=Now())
        self.refresh_from_db()
