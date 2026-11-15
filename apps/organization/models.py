import uuid

from django.conf import settings
from django.db import models


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
