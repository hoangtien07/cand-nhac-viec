"""EU-04 (SPEC FEEDBACK V2): tạo PHIÊN BẢN NHÁP KPI 15 điểm cho loại DOCUMENT.

Dải trừ theo đề xuất phản ánh (D01–D02 CHƯA chốt → KHÔNG publish):
  Nhắc nhở: 0 lần:0%, 1:25%, 2:50%, 3:75%, >=4:100%
  Trễ hạn : 0 ngày:0%, 1-5:25%, 6-7:50%, 8-10:75%, >=11:100%

Actor cần CONFIG_EDIT (mặc định 'lanhdao.a1'); clone tiêu chí từ ACTIVE hiện tại.
Idempotent: nếu đã có DRAFT 15.00 cùng tên trong family DOCUMENT thì bỏ qua.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.kpi import services
from apps.kpi.models import (
    CombinationStrategy,
    KpiPolicyFamily,
    PenaltyBandKind,
    PolicyVersionStatus,
)
from apps.records.models import TaskKind

NAME = "Thang điểm công tác 15 điểm – đề xuất"
BANDS = [
    # LATE_DAYS (đề xuất; Excel gốc chồng ở 5 và 7 — đã chọn khớp liền mạch, D01)
    {"kind": PenaltyBandKind.LATE_DAYS, "min_value": 0, "max_value": 0, "deduction_percent": Decimal("0")},
    {"kind": PenaltyBandKind.LATE_DAYS, "min_value": 1, "max_value": 5, "deduction_percent": Decimal("25")},
    {"kind": PenaltyBandKind.LATE_DAYS, "min_value": 6, "max_value": 7, "deduction_percent": Decimal("50")},
    {"kind": PenaltyBandKind.LATE_DAYS, "min_value": 8, "max_value": 10, "deduction_percent": Decimal("75")},
    {
        "kind": PenaltyBandKind.LATE_DAYS,
        "min_value": 11,
        "max_value": None,
        "deduction_percent": Decimal("100"),
    },
    # REMINDER_COUNT
    {
        "kind": PenaltyBandKind.REMINDER_COUNT,
        "min_value": 0,
        "max_value": 0,
        "deduction_percent": Decimal("0"),
    },
    {
        "kind": PenaltyBandKind.REMINDER_COUNT,
        "min_value": 1,
        "max_value": 1,
        "deduction_percent": Decimal("25"),
    },
    {
        "kind": PenaltyBandKind.REMINDER_COUNT,
        "min_value": 2,
        "max_value": 2,
        "deduction_percent": Decimal("50"),
    },
    {
        "kind": PenaltyBandKind.REMINDER_COUNT,
        "min_value": 3,
        "max_value": 3,
        "deduction_percent": Decimal("75"),
    },
    {
        "kind": PenaltyBandKind.REMINDER_COUNT,
        "min_value": 4,
        "max_value": None,
        "deduction_percent": Decimal("100"),
    },
]


class Command(BaseCommand):
    help = "Tạo phiên bản KPI DRAFT 15 điểm (clone ACTIVE); KHÔNG kích hoạt."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="lanhdao.a1", help="Username có CONFIG_EDIT")

    @transaction.atomic
    def handle(self, *args, **opts):
        actor = User.objects.get(username=opts["actor"])
        family = KpiPolicyFamily.objects.filter(unit_id=actor.unit_id, task_kind=TaskKind.DOCUMENT).first()
        if family is None:
            raise CommandError("Chưa có family KPI DOCUMENT — seed/publish cấu hình gốc trước.")
        # name nằm trên family, không phải version — kiểm theo family.name + max_points.
        existing = (
            family.versions.filter(status=PolicyVersionStatus.DRAFT, max_points=Decimal("15.00")).first()
            if family.name == NAME
            else None
        )
        if existing:
            self.stdout.write(f"Đã có DRAFT v{existing.version} «{NAME}» — bỏ qua.")
            return
        active = family.versions.filter(status=PolicyVersionStatus.ACTIVE).first()
        version = services.create_draft(
            actor,
            task_kind=TaskKind.DOCUMENT,
            name=NAME,
            max_points=Decimal("15.00"),
            combination_strategy=CombinationStrategy.CAPPED_ADDITIVE,
            clone_from_id=active.pk if active else None,
        )
        services.replace_penalty_bands(actor, version.pk, BANDS)
        self.stdout.write(
            self.style.SUCCESS(
                f"Tạo DRAFT v{version.version} «{NAME}» (max 15.00, "
                f"{len(BANDS)} dải trừ) — KHÔNG publish, chờ duyệt D01–D04."
            )
        )
