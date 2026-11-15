from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.organization.models import Department

from .models import Role, User


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Tên đăng nhập hoặc mật khẩu không đúng.",
        "inactive": "Tên đăng nhập hoặc mật khẩu không đúng.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Tên đăng nhập"
        self.fields["password"].label = "Mật khẩu"


class _UnitScopedUserForm(forms.ModelForm):
    def __init__(self, admin, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin = admin
        self.fields["department"].queryset = Department.objects.filter(unit_id=admin.unit_id, is_active=True)
        self.fields["department"].required = False

    def clean(self):
        cd = super().clean()
        role, dept = cd.get("role"), cd.get("department")
        if role in (Role.DEPT_MANAGER, Role.OFFICER) and not dept:
            self.add_error("department", "Cán bộ và trưởng phòng cần có phòng/đội chính.")
        if dept and dept.unit_id != self.admin.unit_id:
            self.add_error("department", "Phòng/đội không thuộc đơn vị của bạn.")
        return cd


class UserCreateForm(_UnitScopedUserForm):
    password1 = forms.CharField(label="Mật khẩu ban đầu", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="Nhập lại mật khẩu", widget=forms.PasswordInput, strip=False)

    class Meta:
        model = User
        fields = ["username", "full_name", "role", "department"]

    def clean(self):
        cd = super().clean()
        if cd.get("password1") != cd.get("password2"):
            self.add_error("password2", "Hai mật khẩu không khớp.")
        elif cd.get("password1"):
            probe = User(username=cd.get("username", ""), full_name=cd.get("full_name", ""))
            try:
                password_validation.validate_password(cd["password1"], probe)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cd


class UserEditForm(_UnitScopedUserForm):
    class Meta:
        model = User
        fields = ["full_name", "role", "department", "is_active"]

    def clean(self):
        cd = super().clean()
        if self.instance.pk == self.admin.pk:
            if cd.get("role") != self.instance.role or not cd.get("is_active", True):
                raise forms.ValidationError("Không thể tự đổi vai trò hoặc tự khóa tài khoản của chính mình.")
        return cd


class AdminSetPasswordForm(forms.Form):
    password1 = forms.CharField(label="Mật khẩu mới", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="Nhập lại", widget=forms.PasswordInput, strip=False)

    def __init__(self, target, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target

    def clean(self):
        cd = super().clean()
        if cd.get("password1") != cd.get("password2"):
            raise forms.ValidationError("Hai mật khẩu không khớp.")
        if cd.get("password1"):
            password_validation.validate_password(cd["password1"], self.target)
        return cd


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "manager", "is_active"]

    def __init__(self, admin, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin = admin
        self.fields["manager"].queryset = User.objects.filter(
            unit_id=admin.unit_id, role=Role.DEPT_MANAGER, is_active=True
        )
        self.fields["manager"].required = False

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        dup = Department.objects.filter(unit_id=self.admin.unit_id, name__iexact=name).exclude(
            pk=self.instance.pk
        )
        if dup.exists():
            raise forms.ValidationError("Đã có phòng/đội cùng tên trong đơn vị.")
        return name
