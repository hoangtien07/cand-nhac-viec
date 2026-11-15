from django.core.management.base import BaseCommand

from apps.notifications.services import run_due_reminders


class Command(BaseCommand):
    help = "Tạo nhắc hạn trong web (D-1, đến hạn, quá hạn). Idempotent: chạy lặp không tạo trùng."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Chạy cả trước giờ nhắc buổi sáng.")

    def handle(self, *args, **opts):
        out = run_due_reminders(force=opts["force"])
        if out["skipped"]:
            self.stdout.write("Bỏ qua: chưa đến giờ nhắc buổi sáng (dùng --force để chạy ngay).")
        else:
            self.stdout.write(f"records={out['records']} created={out['created']}")
