"""EU-02 (SPEC FEEDBACK V2): đổi tên 5 tổ demo của 'Công an phường A (giả lập)'
từ 'Tổ Công tác i (giả lập)' sang danh mục đúng phản ánh — theo UUID hiện hữu,
không tạo tổ mới, mọi FK (user/record/plan/grant/audit) giữ nguyên.

Idempotent theo tên cũ: chạy trên DB chưa seed hoặc đã đổi tên thì no-op.
Tên đích chuẩn hóa 'Tổ Cảnh sát trật tự' (Excel gốc 'trậ tự' — D09).
"""

from django.db import migrations

RENAME = {
    "Tổ Công tác 1 (giả lập)": "Tổ An ninh (giả lập)",
    "Tổ Công tác 2 (giả lập)": "Tổ Tham mưu Tổng hợp (giả lập)",
    "Tổ Công tác 3 (giả lập)": "Tổ Cảnh sát khu vực (giả lập)",
    "Tổ Công tác 4 (giả lập)": "Tổ Cảnh sát Phòng chống tội phạm (giả lập)",
    "Tổ Công tác 5 (giả lập)": "Tổ Cảnh sát trật tự (giả lập)",
}
UNIT_NAME = "Công an phường A (giả lập)"


def forwards(apps, schema_editor):
    Unit = apps.get_model("organization", "Unit")
    Department = apps.get_model("organization", "Department")
    unit = Unit.objects.filter(name=UNIT_NAME).first()
    if unit is None:
        return
    for old, new in RENAME.items():
        # Va chạm: tên đích đã tồn tại trong unit → bỏ qua (unique(unit, name)).
        if Department.objects.filter(unit=unit, name=new).exists():
            continue
        Department.objects.filter(unit=unit, name=old).update(name=new)


def backwards(apps, schema_editor):
    Unit = apps.get_model("organization", "Unit")
    Department = apps.get_model("organization", "Department")
    unit = Unit.objects.filter(name=UNIT_NAME).first()
    if unit is None:
        return
    for old, new in RENAME.items():
        if Department.objects.filter(unit=unit, name=old).exists():
            continue
        Department.objects.filter(unit=unit, name=new).update(name=old)


class Migration(migrations.Migration):
    dependencies = [
        ("organization", "0002_workfolder_foldergrant_and_more"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
