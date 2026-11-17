import datetime
import re

from django import forms

from . import policies
from .codes import MAX_CODE_LENGTH, InvalidCode, clean_display_code
from .models import TaskKind
from .timeutils import db_now, local_date


class UserChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        dept = obj.department.name if obj.department_id else "—"
        return f"{obj.full_name} · {dept} · {obj.get_role_display()}"


def _user_qs(qs):
    return qs.select_related("department").order_by("department__name", "full_name")


class DueDateMixin:
    def clean_due_date(self):
        day = self.cleaned_data["due_date"]
        if day < local_date(db_now()):
            raise forms.ValidationError("Hạn xử lý không được ở quá khứ.")
        return day


class RecordCreateForm(DueDateMixin, forms.Form):
    task_kind = forms.ChoiceField(
        label="Loại nhiệm vụ",
        choices=TaskKind.choices,
        initial=TaskKind.DOCUMENT,
        widget=forms.RadioSelect,
    )
    title = forms.CharField(
        label="Tên nhiệm vụ (bắt buộc cho «Nhiệm vụ khác»)", max_length=200, required=False
    )
    task_code = forms.CharField(label="Mã nhiệm vụ nội bộ (không bắt buộc)", max_length=64, required=False)
    reference_no = forms.CharField(
        label="Số hiệu gốc",
        max_length=MAX_CODE_LENGTH,
        required=False,
        help_text="Bắt buộc cho văn bản. Ví dụ: CV-123/2026. Chỉ nhập số hiệu, không nhập nội dung hồ sơ.",
    )
    owner_department = forms.ModelChoiceField(label="Phòng/đội chủ trì", queryset=None, empty_label=None)
    due_date = forms.DateField(
        label="Hạn xử lý",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Hết hạn lúc 23:59 ngày đã chọn (giờ Việt Nam).",
    )
    description_short = forms.CharField(
        label="Ghi chú/mô tả ngắn (không bắt buộc)", max_length=200, required=False
    )
    assignees = UserChoiceField(
        label="Người xử lý (ít nhất 1)", queryset=None, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["owner_department"].queryset = policies.creatable_departments(user)
        self.fields["assignees"].queryset = _user_qs(policies.assignable_users(user, None))

    def clean_reference_no(self):
        value = (self.cleaned_data.get("reference_no") or "").strip()
        if not value:
            return ""
        try:
            return clean_display_code(value)
        except InvalidCode as e:
            raise forms.ValidationError(str(e)) from e

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("task_kind")
        if kind == TaskKind.DOCUMENT and not cleaned.get("reference_no"):
            self.add_error("reference_no", "Văn bản bắt buộc có số hiệu.")
        if kind == TaskKind.OTHER and not (cleaned.get("title") or "").strip():
            self.add_error("title", "Nhiệm vụ khác bắt buộc có tên nhiệm vụ.")
        return cleaned


class PeriodicPlanForm(forms.Form):
    """STT10/WP2: một kế hoạch định kỳ → 1..12 kỳ (WorkRecord con), hạn mỗi kỳ một dòng."""

    name = forms.CharField(label="Tên văn bản/nhiệm vụ định kỳ", max_length=200)
    task_kind = forms.ChoiceField(
        label="Loại nhiệm vụ",
        choices=TaskKind.choices,
        initial=TaskKind.DOCUMENT,
        widget=forms.RadioSelect,
    )
    reference_no = forms.CharField(
        label="Số hiệu chung (không bắt buộc)", max_length=MAX_CODE_LENGTH, required=False
    )
    task_code = forms.CharField(label="Mã nhiệm vụ nội bộ (không bắt buộc)", max_length=64, required=False)
    owner_department = forms.ModelChoiceField(label="Phòng/đội chủ trì", queryset=None, empty_label=None)
    year = forms.IntegerField(label="Năm áp dụng", min_value=2000, max_value=2100)
    due_dates = forms.CharField(
        label="Ngày hạn các kỳ — một ngày mỗi dòng (1–12 dòng)",
        widget=forms.Textarea(
            attrs={"rows": 12, "placeholder": "2026-03-31\n2026-06-30\n2026-09-30\n2026-12-31"}
        ),
        help_text="Định dạng YYYY-MM-DD. Tất cả ngày phải thuộc năm áp dụng, không trùng nhau.",
    )
    description_short = forms.CharField(
        label="Ghi chú/mô tả ngắn (không bắt buộc)", max_length=200, required=False
    )
    assignees = UserChoiceField(
        label="Người xử lý cho mọi kỳ (ít nhất 1)", queryset=None, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_department"].queryset = policies.creatable_departments(user)
        self.fields["assignees"].queryset = _user_qs(policies.assignable_users(user, None))
        if not self.is_bound:
            self.fields["year"].initial = local_date(db_now()).year

    def clean_reference_no(self):
        value = (self.cleaned_data.get("reference_no") or "").strip()
        if not value:
            return ""
        try:
            return clean_display_code(value)
        except InvalidCode as e:
            raise forms.ValidationError(str(e)) from e

    def clean_due_dates(self):
        raw = self.cleaned_data["due_dates"]
        days = []
        errors = []
        for line in re.split(r"[\n,;]+", raw):
            line = line.strip()
            if not line:
                continue
            try:
                days.append(datetime.date.fromisoformat(line))
            except ValueError:
                errors.append(f"«{line}» không đúng định dạng YYYY-MM-DD.")
        if errors:
            raise forms.ValidationError(errors)
        if not days:
            raise forms.ValidationError("Cần ít nhất một ngày hạn.")
        return days


class AssignmentForm(forms.Form):
    assignees = UserChoiceField(label="Người xử lý", queryset=None, widget=forms.CheckboxSelectMultiple)

    def __init__(self, user, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignees"].queryset = _user_qs(policies.assignable_users(user, record.owner_department))


# STT2/D13: no new watchers via UI. WatchersForm removed; the update_watchers service stays
# for legacy data maintenance only — it is no longer reachable from any view.


class DeadlineForm(DueDateMixin, forms.Form):
    due_date = forms.DateField(label="Hạn xử lý mới", widget=forms.DateInput(attrs={"type": "date"}))


class SubmitResultForm(forms.Form):
    code = forms.CharField(
        label="Số hiệu kết quả",
        max_length=MAX_CODE_LENGTH,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "VD: KQ-2026-001"}),
    )

    def clean_code(self):
        try:
            return clean_display_code(self.cleaned_data["code"])
        except InvalidCode as e:
            raise forms.ValidationError(str(e)) from e


class RecordEditForm(forms.Form):
    """Metadata edit for OPEN, non-archived records. Each changed field is applied through its
    own audited service; the whole edit is one transaction (all-or-nothing)."""

    reference_no = forms.CharField(label="Số hiệu hồ sơ gốc", max_length=MAX_CODE_LENGTH)
    owner_department = forms.ModelChoiceField(label="Phòng/đội chủ trì", queryset=None, empty_label=None)
    folder = forms.ModelChoiceField(
        label="Nhóm hồ sơ", queryset=None, required=False, empty_label="— Không thuộc nhóm —"
    )
    due_date = forms.DateField(label="Hạn xử lý", widget=forms.DateInput(attrs={"type": "date"}))
    description_short = forms.CharField(
        label="Ghi chú/mô tả ngắn (không bắt buộc)", max_length=200, required=False
    )
    assignees = UserChoiceField(
        label="Người xử lý (ít nhất 1)", queryset=None, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, user, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organization.folder_policies import movable_folders

        self.fields["owner_department"].queryset = policies.creatable_departments(user)
        self.fields["folder"].queryset = movable_folders(user, record)
        self.fields["assignees"].queryset = _user_qs(policies.assignable_users(user, record.owner_department))

    def clean_reference_no(self):
        try:
            return clean_display_code(self.cleaned_data["reference_no"])
        except InvalidCode as e:
            raise forms.ValidationError(str(e)) from e


class ArchiveForm(forms.Form):
    reason = forms.CharField(
        label="Lý do lưu trữ",
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "VD: Trùng hồ sơ, tạo nhầm"}),
    )


class CorrectionForm(forms.Form):
    new_code = forms.CharField(
        label="Số hiệu thay thế",
        max_length=MAX_CODE_LENGTH,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    reason = forms.CharField(label="Lý do đính chính", max_length=300)

    def clean_new_code(self):
        try:
            return clean_display_code(self.cleaned_data["new_code"])
        except InvalidCode as e:
            raise forms.ValidationError(str(e)) from e


class RevokeResultForm(forms.Form):
    reason = forms.CharField(label="Lý do hủy hiệu lực", max_length=300)
    confirm = forms.BooleanField(label="Tôi xác nhận hủy hiệu lực số hiệu này")


class RecordFilterForm(forms.Form):
    STATUS_CHOICES = [
        ("", "Tất cả trạng thái"),
        ("OPEN", "Đang xử lý"),
        ("DUE_SOON", "Sắp đến hạn"),
        ("OVERDUE", "Quá hạn"),
        ("DONE", "Đã hoàn thành"),
        ("ARCHIVED", "Đã lưu trữ"),
    ]
    q = forms.CharField(label="Tìm số hiệu", required=False, max_length=MAX_CODE_LENGTH)
    department = forms.ModelChoiceField(
        label="Phòng chủ trì", queryset=None, required=False, empty_label="Tất cả phòng"
    )
    folder = forms.ModelChoiceField(
        label="Nhóm hồ sơ", queryset=None, required=False, empty_label="Tất cả nhóm"
    )
    status = forms.ChoiceField(label="Trạng thái", choices=STATUS_CHOICES, required=False)
    assignee = forms.ModelChoiceField(
        label="Người xử lý", queryset=None, required=False, empty_label="Tất cả"
    )
    creator = forms.ModelChoiceField(label="Người tạo", queryset=None, required=False, empty_label="Tất cả")
    due_from = forms.DateField(label="Hạn từ", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    due_to = forms.DateField(label="Hạn đến", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    assigned_to_me = forms.BooleanField(label="Giao cho tôi", required=False)
    shared_with_me = forms.BooleanField(label="Chia sẻ với tôi", required=False)

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User
        from apps.organization import folder_policies
        from apps.organization.models import Department

        visible_depts = policies.visible_records_queryset(user).values("owner_department_id")
        self.fields["department"].queryset = Department.objects.filter(id__in=visible_depts)
        self.fields["folder"].queryset = folder_policies.visible_folders_queryset(user)
        unit_users = User.objects.filter(unit_id=user.unit_id, is_active=True).order_by("full_name")
        self.fields["assignee"].queryset = unit_users
        self.fields["creator"].queryset = unit_users
