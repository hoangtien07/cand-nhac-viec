from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Role(models.TextChoices):
    SYS_ADMIN = "SYS_ADMIN", "Quản trị kỹ thuật"
    LEADER = "LEADER", "Lãnh đạo đơn vị"
    DEPT_MANAGER = "DEPT_MANAGER", "Trưởng phòng/đội"
    OFFICER = "OFFICER", "Cán bộ"


BUSINESS_ROLES = (Role.LEADER, Role.DEPT_MANAGER, Role.OFFICER)


class User(AbstractUser):
    """Custom user. `is_staff`/`is_superuser` never grant access to business records."""

    email = None
    first_name = None
    last_name = None
    full_name = models.CharField("Họ tên", max_length=150)
    unit = models.ForeignKey(
        "organization.Unit",
        verbose_name="Đơn vị",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    department = models.ForeignKey(
        "organization.Department",
        verbose_name="Phòng/đội chính",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="members",
    )
    role = models.CharField("Vai trò", max_length=20, choices=Role.choices, default=Role.OFFICER)

    EMAIL_FIELD = None
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "Tài khoản"
        ordering = ["full_name", "username"]

    def __str__(self):
        return self.full_name or self.username

    def clean(self):
        super().clean()
        if self.department_id and self.department.unit_id != self.unit_id:
            raise ValidationError({"department": "Phòng/đội phải thuộc cùng đơn vị với tài khoản."})

    @property
    def is_business_user(self):
        return bool(self.is_active and self.unit_id and self.role in BUSINESS_ROLES)

    @property
    def is_sys_admin(self):
        return bool(self.is_active and self.unit_id and self.role == Role.SYS_ADMIN)
