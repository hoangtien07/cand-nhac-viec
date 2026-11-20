"""EU-02 (SPEC FEEDBACK V2): chuẩn hóa tài khoản demo trên DB đã tồn tại.

- Thu hồi grant KPI của leader.config/leader.approve và khóa 2 tài khoản đó
  (is_active=False — chỉ trên môi trường demo khi được chủ động chạy).
- Cấp capability KPI cho 2 lãnh đạo nghiệp vụ: lanhdao.a1 (soạn/nhắc/chấm),
  lanhdao.a2 (duyệt/chốt/xem) — phản ánh tách trách nhiệm D06/D09.

Idempotent: chạy lại không tạo trùng grant, không đụng mật khẩu/tài khoản khác.
Chỉ tác động unit 'Công an phường A (giả lập)'; không xóa cứng bản ghi nào.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.kpi.capabilities import KpiCapability
from apps.kpi.models import GrantScope, KpiCapabilityGrant
from apps.organization.models import Unit

UNIT_NAME = "Công an phường A (giả lập)"
LEGACY_LEADERS = ["leader.config", "leader.approve"]
GRANTS = {
    "lanhdao.a1": [
        KpiCapability.CONFIG_EDIT,
        KpiCapability.REMINDER_ISSUE,
        KpiCapability.EVALUATE,
    ],
    "lanhdao.a2": [
        KpiCapability.CONFIG_PUBLISH,
        KpiCapability.SCORE_FINALIZE,
        KpiCapability.VIEW_UNIT,
    ],
}


class Command(BaseCommand):
    help = "Chuẩn hóa 2 lãnh đạo nghiệp vụ demo: khóa leader.config/approve, cấp grant cho lanhdao.a1/a2."

    def add_arguments(self, parser):
        parser.add_argument(
            "--deactivate",
            action="store_true",
            help="Khóa leader.config/leader.approve (is_active=False). "
            "D06 chưa chốt → mặc định chỉ thu hồi grant.",
        )

    def handle(self, *args, **opts):
        unit = Unit.objects.filter(name=UNIT_NAME).first()
        if unit is None:
            self.stdout.write("Không có đơn vị demo — bỏ qua.")
            return
        with transaction.atomic():
            admin = User.objects.get(username="admin.a")
            for username in LEGACY_LEADERS:
                user = User.objects.filter(username=username, unit=unit).first()
                if user is None:
                    continue
                revoked = KpiCapabilityGrant.objects.filter(
                    unit=unit, user=user, revoked_at__isnull=True
                ).update(revoked_at=timezone.now())
                if opts["deactivate"] and user.is_active:
                    user.is_active = False
                    user.save(update_fields=["is_active"])
                self.stdout.write(f"  {username}: thu hồi {revoked} grant"
                                  + (", đã khóa" if opts["deactivate"] else ""))
            created = 0
            for username, caps in GRANTS.items():
                user = User.objects.get(username=username)
                for cap in caps:
                    _, was = KpiCapabilityGrant.objects.get_or_create(
                        unit=unit,
                        user=user,
                        capability=cap,
                        scope=GrantScope.UNIT,
                        defaults={
                            "granted_by": admin,
                            "approved_by": admin,
                            "reason": "EU-02: chuẩn hóa 2 lãnh đạo nghiệp vụ demo",
                        },
                    )
                    created += int(was)
        self.stdout.write(self.style.SUCCESS(f"Xong: {created} grant mới."))
