"""Synthetic demo data (ACCEPTANCE §2). No real names, codes or organizations.

Passwords: DEMO_SEED_PASSWORD env (one shared password chosen by the operator) or a random
password per account written to a 0600 file. Never a fixed default password.
"""

import datetime
import os
import secrets
import stat
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.notifications.services import remind_record
from apps.organization.models import Department, Unit
from apps.records import services
from apps.records.models import WorkRecord
from apps.records.timeutils import db_now, local_date

UNITS = {
    "A": ("Đơn vị Giả lập A", ["Phòng Tổng hợp", "Phòng Địa bàn"]),
    "B": ("Đơn vị Giả lập B", ["Phòng Nội bộ", "Phòng Hành chính"]),
}
# (username, full name, unit, dept index or None, role)
ACCOUNTS = [
    ("admin.a", "Quản trị A (giả lập)", "A", None, Role.SYS_ADMIN),
    ("lanhdao.a", "Lãnh đạo A (giả lập)", "A", 0, Role.LEADER),
    ("truongphong.th", "Trưởng phòng Tổng hợp (giả lập)", "A", 0, Role.DEPT_MANAGER),
    ("truongphong.db", "Trưởng phòng Địa bàn (giả lập)", "A", 1, Role.DEPT_MANAGER),
    ("canbo.th1", "Cán bộ Tổng hợp 1 (giả lập)", "A", 0, Role.OFFICER),
    ("canbo.th2", "Cán bộ Tổng hợp 2 (giả lập)", "A", 0, Role.OFFICER),
    ("canbo.db1", "Cán bộ Địa bàn 1 (giả lập)", "A", 1, Role.OFFICER),
    ("canbo.db2", "Cán bộ Địa bàn 2 (giả lập)", "A", 1, Role.OFFICER),
    ("admin.b", "Quản trị B (giả lập)", "B", None, Role.SYS_ADMIN),
    ("lanhdao.b", "Lãnh đạo B (giả lập)", "B", 0, Role.LEADER),
    ("truongphong.nb", "Trưởng phòng Nội bộ (giả lập)", "B", 0, Role.DEPT_MANAGER),
    ("truongphong.hc", "Trưởng phòng Hành chính (giả lập)", "B", 1, Role.DEPT_MANAGER),
    ("canbo.nb1", "Cán bộ Nội bộ 1 (giả lập)", "B", 0, Role.OFFICER),
    ("canbo.nb2", "Cán bộ Nội bộ 2 (giả lập)", "B", 0, Role.OFFICER),
    ("canbo.hc1", "Cán bộ Hành chính 1 (giả lập)", "B", 1, Role.OFFICER),
]


class Command(BaseCommand):
    help = "Tạo dữ liệu demo GIẢ LẬP (2 đơn vị, 4 phòng, 15 tài khoản, hồ sơ R1..R5). Chỉ chạy trên DB rỗng."

    def add_arguments(self, parser):
        parser.add_argument("--credentials-file", default="var/demo_credentials.txt")

    def handle(self, *args, **opts):
        if Unit.objects.exists() or User.objects.exists():
            raise CommandError(
                "DB đã có dữ liệu; seed_demo chỉ chạy trên DB rỗng (xem README_RUN.md để reset)."
            )
        shared = os.environ.get("DEMO_SEED_PASSWORD")
        creds = []
        with transaction.atomic():
            units, depts, users = {}, {}, {}
            for key, (name, dnames) in UNITS.items():
                units[key] = Unit.objects.create(name=name)
                depts[key] = [Department.objects.create(unit=units[key], name=d) for d in dnames]
            for username, full_name, ukey, didx, role in ACCOUNTS:
                pw = shared or secrets.token_urlsafe(12)
                u = User(
                    username=username,
                    full_name=full_name,
                    unit=units[ukey],
                    role=role,
                    department=depts[ukey][didx] if didx is not None else None,
                )
                u.set_password(pw)
                u.save()
                users[username] = u
                creds.append((username, pw))
            for ukey, (dth, ddb) in {
                "A": ("truongphong.th", "truongphong.db"),
                "B": ("truongphong.nb", "truongphong.hc"),
            }.items():
                Department.objects.filter(pk=depts[ukey][0].pk).update(manager=users[dth])
                Department.objects.filter(pk=depts[ukey][1].pk).update(manager=users[ddb])
            for d in depts["A"] + depts["B"]:
                d.refresh_from_db()
            self._records(users, depts)
        if not shared:
            path = Path(opts["credentials_file"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(f"{u}\t{p}\n" for u, p in creds), encoding="utf-8")
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            self.stdout.write(f"Mật khẩu ngẫu nhiên đã ghi vào {path} (quyền 0600).")
        self.stdout.write(
            self.style.SUCCESS(f"Seed xong: {len(creds)} tài khoản, {WorkRecord.objects.count()} hồ sơ.")
        )

    def _records(self, u, depts):
        today = local_date(db_now())
        d = datetime.timedelta
        th, db = depts["A"]
        nb, _hc = depts["B"]
        r1 = services.create_record(
            u["canbo.th1"],
            reference_no="GL-001/2026",
            owner_department=th,
            due_date=today + d(days=1),
            assignees=[u["canbo.th1"], u["canbo.th2"]],
            watchers=[u["truongphong.th"]],
        )
        r2 = services.create_record(
            u["lanhdao.a"],
            reference_no="GL-002/2026",
            owner_department=th,
            due_date=today + d(days=5),
            assignees=[u["canbo.th2"], u["canbo.db1"]],
            watchers=[],
        )
        # R2 must be overdue: backdate the deadline directly (demo fixture only; bypasses the
        # "no past deadline" form rule on purpose) and generate its reminders.
        WorkRecord.objects.filter(pk=r2.pk).update(due_at=r2.due_at - d(days=8))
        r3 = services.create_record(
            u["truongphong.db"],
            reference_no="GL-003/2026",
            owner_department=db,
            due_date=today + d(days=3),
            assignees=[u["canbo.db1"], u["canbo.db2"]],
            watchers=[u["canbo.th1"]],
        )
        services.submit_result_reference(u["canbo.db1"], r3.pk, "KQ-GL-0301")
        services.submit_result_reference(u["canbo.db2"], r3.pk, "KQ-GL-0302")
        services.create_record(
            u["canbo.nb1"],
            reference_no="GL-001/2026",
            owner_department=nb,
            due_date=today + d(days=2),
            assignees=[u["canbo.nb1"], u["canbo.nb2"]],
            watchers=[],
        )
        services.create_record(
            u["canbo.db2"],
            reference_no="GL-005/2026",
            owner_department=db,
            due_date=today + d(days=10),
            assignees=[u["canbo.db2"]],
            watchers=[u["canbo.th2"]],
        )
        services.create_record(
            u["lanhdao.a"],
            reference_no="GL-006/2026",
            owner_department=th,
            due_date=today,
            assignees=[u["canbo.th1"], u["canbo.th2"], u["canbo.db2"]],
            watchers=[u["truongphong.db"], u["canbo.db1"]],
        )
        for rec in (r1, r2):
            remind_record(rec.pk)
