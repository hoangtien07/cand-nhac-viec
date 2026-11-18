"""Synthetic demo data (ACCEPTANCE §2 + plan STT8/STT9/STT12). No real names, codes or
organizations — "Công an phường A" is a labeled demo placeholder per the plan.

Passwords: DEMO_SEED_PASSWORD env (one shared password chosen by the operator) or a random
password per account written to a 0600 file. Never a fixed default password.

Idempotent: existing units/departments/users/records are left untouched; only missing
rows are created. Re-running is a no-op on a seeded DB.
"""

import datetime
import os
import secrets
import stat
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.notifications.services import remind_record
from apps.organization.models import Department, Unit
from apps.records import services
from apps.records.models import WorkRecord
from apps.records.timeutils import db_now, local_date

DEPT_NAMES = [f"Tổ Công tác {i} (giả lập)" for i in range(1, 6)]
UNITS = {
    "A": ("Công an phường A (giả lập)", DEPT_NAMES),
    "B": ("Đơn vị giả lập B", ["Phòng Nội bộ", "Phòng Hành chính"]),
}
# (username, full name, unit, dept index or None, role)
ACCOUNTS = [
    ("admin.a", "Quản trị A (giả lập)", "A", None, Role.SYS_ADMIN),
    ("lanhdao.a1", "Lãnh đạo A1 (giả lập)", "A", None, Role.LEADER),
    ("lanhdao.a2", "Lãnh đạo A2 (giả lập)", "A", None, Role.LEADER),
    # Tách trách nhiệm demo (plan D09): một leader soạn cấu hình + chấm, một leader duyệt + chốt.
    ("leader.config", "Lãnh đạo cấu hình KPI (giả lập)", "A", None, Role.LEADER),
    ("leader.approve", "Lãnh đạo phê duyệt KPI (giả lập)", "A", None, Role.LEADER),
    *[(f"canbo.to{i}", f"Cán bộ Tổ {i} (giả lập)", "A", i - 1, Role.OFFICER) for i in range(1, 6)],
    ("admin.b", "Quản trị B (giả lập)", "B", None, Role.SYS_ADMIN),
    ("lanhdao.b", "Lãnh đạo B (giả lập)", "B", 0, Role.LEADER),
    ("truongphong.nb", "Trưởng phòng Nội bộ (giả lập)", "B", 0, Role.DEPT_MANAGER),
    ("truongphong.hc", "Trưởng phòng Hành chính (giả lập)", "B", 1, Role.DEPT_MANAGER),
    ("canbo.nb1", "Cán bộ Nội bộ 1 (giả lập)", "B", 0, Role.OFFICER),
    ("canbo.nb2", "Cán bộ Nội bộ 2 (giả lập)", "B", 0, Role.OFFICER),
]


class Command(BaseCommand):
    help = "Tạo dữ liệu demo GIẢ LẬP idempotent (phường A: 5 tổ, 2 lãnh đạo, 5 cán bộ + đơn vị B)."

    def add_arguments(self, parser):
        parser.add_argument("--credentials-file", default="var/demo_credentials.txt")

    def handle(self, *args, **opts):
        shared = os.environ.get("DEMO_SEED_PASSWORD")
        creds = []
        with transaction.atomic():
            units, depts, users = {}, {}, {}
            for key, (name, dnames) in UNITS.items():
                units[key], _ = Unit.objects.get_or_create(name=name)
                depts[key] = [
                    Department.objects.get_or_create(unit=units[key], name=d)[0] for d in dnames
                ]
            for username, full_name, ukey, didx, role in ACCOUNTS:
                u, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "full_name": full_name,
                        "unit": units[ukey],
                        "role": role,
                        "department": depts[ukey][didx] if didx is not None else None,
                    },
                )
                if created:
                    pw = shared or secrets.token_urlsafe(12)
                    u.set_password(pw)
                    u.save()
                    creds.append((username, pw))
                users[username] = u
            if not WorkRecord.objects.exists():
                self._records(users, depts)
            self._kpi_grants(users, units)
        if creds and not shared:
            path = Path(opts["credentials_file"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(f"{u}\t{p}\n" for u, p in creds), encoding="utf-8")
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            self.stdout.write(f"Mật khẩu ngẫu nhiên đã ghi vào {path} (quyền 0600).")
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed xong: {len(creds)} tài khoản mới, {WorkRecord.objects.count()} hồ sơ."
            )
        )

    def _kpi_grants(self, u, units):
        """Demo capability grants (PLAN §STT?): leader.config = CONFIG_EDIT+EVALUATE,
        leader.approve = PUBLISH+SCORE_FINALIZE+VIEW_UNIT. SYS_ADMIN không có grant nghiệp vụ."""
        from apps.kpi.capabilities import KpiCapability
        from apps.kpi.models import GrantScope, KpiCapabilityGrant

        granter = u["admin.a"]
        unit = units["A"]
        for username, caps in (
            ("leader.config", [KpiCapability.CONFIG_EDIT, KpiCapability.EVALUATE]),
            (
                "leader.approve",
                [
                    KpiCapability.CONFIG_PUBLISH,
                    KpiCapability.SCORE_FINALIZE,
                    KpiCapability.VIEW_UNIT,
                ],
            ),
        ):
            for cap in caps:
                KpiCapabilityGrant.objects.get_or_create(
                    unit=unit,
                    user=u[username],
                    capability=cap,
                    scope=GrantScope.UNIT,
                    defaults={
                        "granted_by": granter,
                        "approved_by": granter,
                        "reason": "Seed demo: tách leader.config / leader.approve",
                    },
                )

    def _records(self, u, depts):
        today = local_date(db_now())
        d = datetime.timedelta
        a = depts["A"]
        r1 = services.create_record(
            u["canbo.to1"],
            reference_no="GL-001/2026",
            owner_department=a[0],
            due_date=today + d(days=1),
            assignees=[u["canbo.to1"]],
        )
        r2 = services.create_record(
            u["lanhdao.a1"],
            reference_no="GL-002/2026",
            owner_department=a[1],
            due_date=today + d(days=5),
            assignees=[u["canbo.to2"], u["canbo.to3"]],
        )
        # R2 must be overdue: backdate the deadline directly (demo fixture only; bypasses the
        # "no past deadline" form rule on purpose) and generate its reminders.
        WorkRecord.objects.filter(pk=r2.pk).update(due_at=r2.due_at - d(days=8))
        r3 = services.create_record(
            u["lanhdao.a2"],
            reference_no="GL-003/2026",
            owner_department=a[2],
            due_date=today + d(days=3),
            assignees=[u["canbo.to3"], u["canbo.to4"]],
        )
        services.submit_result_reference(u["canbo.to3"], r3.pk, "KQ-GL-0301")
        services.create_record(
            u["canbo.to5"],
            reference_no="GL-004/2026",
            owner_department=a[4],
            due_date=today + d(days=10),
            assignees=[u["canbo.to5"]],
        )
        nb = depts["B"][0]
        services.create_record(
            u["canbo.nb1"],
            reference_no="GL-001/2026",
            owner_department=nb,
            due_date=today + d(days=2),
            assignees=[u["canbo.nb1"], u["canbo.nb2"]],
        )
        for rec in (r1, r2):
            remind_record(rec.pk)
