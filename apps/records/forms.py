from django import forms

from . import policies
from .codes import MAX_CODE_LENGTH, InvalidCode, clean_display_code
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
    reference_no = forms.CharField(
        label="Số hiệu gốc",
        max_length=MAX_CODE_LENGTH,
        help_text="Ví dụ: CV-123/2026. Chỉ nhập số hiệu, không nhập nội dung hồ sơ.",
    )
    owner_department = forms.ModelChoiceField(label="Phòng/đội chủ trì", queryset=None, empty_label=None)
    due_date = forms.DateField(
        label="Hạn xử lý",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Hết hạn lúc 23:59 ngày đã chọn (giờ Việt Nam).",
    )
    assignees = UserChoiceField(
        label="Người xử lý (ít nhất 1)", queryset=None, widget=forms.CheckboxSelectMultiple
    )
    watchers = UserChoiceField(
        label="Người theo dõi (không bắt buộc)",
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["owner_department"].queryset = policies.creatable_departments(user)
        self.fields["assignees"].queryset = _user_qs(policies.assignable_users(user, None))
        self.fields["watchers"].queryset = _user_qs(policies.watchable_users(user))

    def clean_reference_no(self):
        try:
            return clean_display_code(self.cleaned_data["reference_no"])
        except InvalidCode as e:
            raise forms.ValidationError(str(e)) from e


class AssignmentForm(forms.Form):
    assignees = UserChoiceField(label="Người xử lý", queryset=None, widget=forms.CheckboxSelectMultiple)

    def __init__(self, user, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignees"].queryset = _user_qs(policies.assignable_users(user, record.owner_department))


class WatchersForm(forms.Form):
    watchers = UserChoiceField(
        label="Người theo dõi", queryset=None, required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, user, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["watchers"].queryset = _user_qs(policies.watchable_users(user))


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


class RecordFilterForm(forms.Form):
    STATUS_CHOICES = [
        ("", "Tất cả trạng thái"),
        ("OPEN", "Đang xử lý"),
        ("DUE_SOON", "Sắp đến hạn"),
        ("OVERDUE", "Quá hạn"),
        ("DONE", "Đã hoàn thành"),
    ]
    q = forms.CharField(label="Tìm số hiệu", required=False, max_length=MAX_CODE_LENGTH)
    department = forms.ModelChoiceField(
        label="Phòng chủ trì", queryset=None, required=False, empty_label="Tất cả phòng"
    )
    status = forms.ChoiceField(label="Trạng thái", choices=STATUS_CHOICES, required=False)

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organization.models import Department

        visible_depts = policies.visible_records_queryset(user).values("owner_department_id")
        self.fields["department"].queryset = Department.objects.filter(id__in=visible_depts)
