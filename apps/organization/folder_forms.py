from django import forms

from apps.records import policies as record_policies

from . import folder_policies
from .models import FolderRole, WorkFolder


class FolderCreateForm(forms.Form):
    name = forms.CharField(label="Tên nhóm hồ sơ", max_length=200)
    owner_department = forms.ModelChoiceField(label="Phòng/đội sở hữu", queryset=None, empty_label=None)
    description_short = forms.CharField(
        label="Mô tả ngắn (không bắt buộc)",
        max_length=300,
        required=False,
        help_text="Chỉ mô tả chung, không nhập nội dung hồ sơ hay thông tin nhạy cảm.",
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_department"].queryset = record_policies.creatable_departments(user)


class FolderRenameForm(forms.Form):
    name = forms.CharField(label="Tên mới", max_length=200)


class FolderGrantForm(forms.Form):
    user = forms.ModelChoiceField(label="Thành viên", queryset=None, empty_label=None)
    role = forms.ChoiceField(label="Vai trò", choices=FolderRole.choices, initial=FolderRole.VIEWER)

    def __init__(self, actor, folder, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = folder_policies.grantable_users(actor, folder).order_by(
            "department__name", "full_name"
        )
        self.fields["user"].label_from_instance = lambda u: (
            f"{u.full_name} · {u.department.name if u.department_id else '—'}"
        )


class RecordShareForm(forms.Form):
    user = forms.ModelChoiceField(label="Người được xem hồ sơ này", queryset=None, empty_label=None)

    def __init__(self, actor, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = record_policies.shareable_users(actor, record).order_by(
            "department__name", "full_name"
        )
        self.fields["user"].label_from_instance = lambda u: (
            f"{u.full_name} · {u.department.name if u.department_id else '—'}"
        )


class RecordFolderForm(forms.Form):
    folder = forms.ModelChoiceField(
        label="Nhóm hồ sơ", queryset=None, required=False, empty_label="— Không thuộc nhóm —"
    )

    def __init__(self, actor, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["folder"].queryset = WorkFolder.objects.filter(
            pk__in=folder_policies.movable_folders(actor, record)
        ).order_by("name")
