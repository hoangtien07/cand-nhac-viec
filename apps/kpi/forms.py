from decimal import Decimal

from django import forms
from django.forms import formset_factory

from apps.accounts.models import User
from apps.organization.models import Department
from apps.records.models import TaskKind

from .models import CAPABILITY_CHOICES, CombinationStrategy, GrantScope, PenaltyBandKind


class VersionCreateForm(forms.Form):
    task_kind = forms.ChoiceField(label="Loại nhiệm vụ", choices=TaskKind.choices)
    name = forms.CharField(label="Tên bộ thang điểm", max_length=200)
    max_points = forms.DecimalField(
        label="Thang điểm tối đa", min_value=Decimal("0.01"), max_digits=6, decimal_places=2
    )
    combination_strategy = forms.ChoiceField(
        label="Chiến lược kết hợp mức trừ", choices=CombinationStrategy.choices
    )
    clone_from = forms.UUIDField(label="Sao chép từ phiên bản", required=False)


class VersionMetaForm(forms.Form):
    max_points = forms.DecimalField(
        label="Thang điểm tối đa", min_value=Decimal("0.01"), max_digits=6, decimal_places=2
    )
    combination_strategy = forms.ChoiceField(
        label="Chiến lược kết hợp mức trừ", choices=CombinationStrategy.choices
    )


class CriterionForm(forms.Form):
    code = forms.CharField(label="Mã", max_length=40)
    title = forms.CharField(label="Tên tiêu chí", max_length=200)
    weight_percent = forms.DecimalField(
        label="Trọng số %", min_value=0, max_value=100, max_digits=5, decimal_places=2
    )
    position = forms.IntegerField(label="TT", min_value=0, required=False, initial=0)
    description_short = forms.CharField(label="Mô tả", max_length=200, required=False)
    required = forms.BooleanField(label="Bắt buộc", required=False)


CriterionFormSet = formset_factory(CriterionForm, extra=1, can_delete=True, min_num=1, validate_min=True)


class PenaltyBandForm(forms.Form):
    kind = forms.ChoiceField(label="Loại dải", choices=PenaltyBandKind.choices)
    min_value = forms.IntegerField(label="Từ", min_value=0)
    max_value = forms.IntegerField(label="Đến (để trống = mở)", min_value=0, required=False)
    deduction_percent = forms.DecimalField(
        label="% trừ", min_value=0, max_value=100, max_digits=5, decimal_places=2
    )


PenaltyBandFormSet = formset_factory(PenaltyBandForm, extra=1, can_delete=True, min_num=1, validate_min=True)


class PreviewForm(forms.Form):
    late_days = forms.IntegerField(label="Số ngày trễ", min_value=0, initial=0)
    reminder_count = forms.IntegerField(label="Số lần nhắc nhở", min_value=0, initial=0)
    achievement = forms.DecimalField(
        label="% đạt áp dụng cho mọi tiêu chí (preview nhanh)",
        min_value=0, max_value=100, initial=100, max_digits=5, decimal_places=2,
    )
    strategy = forms.ChoiceField(label="Chiến lược", choices=CombinationStrategy.choices, required=False)


class PublishForm(forms.Form):
    reason = forms.CharField(
        label="Lý do xác nhận kích hoạt", max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "VD: Quyết định số ..."}),
    )


class GrantForm(forms.Form):
    user = forms.ModelChoiceField(label="Tài khoản", queryset=User.objects.none())
    capability = forms.ChoiceField(label="Quyền", choices=CAPABILITY_CHOICES)
    scope = forms.ChoiceField(label="Phạm vi", choices=GrantScope.choices)
    department = forms.ModelChoiceField(
        label="Phòng/đội (bắt buộc khi phạm vi theo tổ)",
        queryset=Department.objects.none(), required=False,
    )
    approved_by = forms.ModelChoiceField(
        label="Người phê duyệt nghiệp vụ", queryset=User.objects.none(), required=False
    )
    reason = forms.CharField(label="Lý do/căn cứ", max_length=200, required=False)

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        if unit is not None:
            members = User.objects.filter(unit=unit, is_active=True).order_by("full_name")
            self.fields["user"].queryset = members
            self.fields["approved_by"].queryset = members
            self.fields["department"].queryset = Department.objects.filter(
                unit=unit, is_active=True
            ).order_by("name")

    def clean(self):
        data = super().clean()
        if data.get("scope") == "DEPARTMENT" and not data.get("department"):
            self.add_error("department", "Chọn phòng/đội cho phạm vi theo tổ.")
        return data
