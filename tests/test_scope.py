"""A25 no extraneous features, A26 synthetic data / no default credentials / deploy settings."""

import re
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.db import models

ROOT = Path(__file__).resolve().parent.parent


def test_no_file_fields_or_subtask_models():
    for m in django_apps.get_models():
        if m._meta.app_label not in {"accounts", "organization", "records", "notifications", "audit"}:
            continue
        for f in m._meta.get_fields():
            assert not isinstance(f, models.FileField), f"{m.__name__}.{f.name}"
        assert "subtask" not in m.__name__.lower()


def test_no_file_inputs_email_or_cdn_in_templates_and_code():
    for p in list((ROOT / "templates").rglob("*.html")):
        t = p.read_text(encoding="utf-8")
        assert 'type="file"' not in t and "multipart/form-data" not in t, p
        assert not re.search(r'src="https?://', t) and not re.search(r'href="https?://', t), p
    for p in (ROOT / "apps").rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        assert "send_mail" not in t and "EmailMessage" not in t and "request.FILES" not in t, p


def test_status_choices_only_open_done():
    from apps.records.models import RecordStatus

    assert set(RecordStatus.values) == {"OPEN", "DONE"}


def test_django_admin_not_mounted():
    from django.urls import resolve
    from django.urls.exceptions import Resolver404

    with pytest.raises(Resolver404):
        resolve("/admin/")


@pytest.mark.django_db
def test_seed_is_synthetic_and_has_no_fixed_password(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_SEED_PASSWORD", raising=False)
    cred = tmp_path / "c.txt"
    call_command("seed_demo", credentials_file=str(cred))
    from apps.accounts.models import User
    from apps.organization.models import Department, Unit
    from apps.records.models import WorkRecord

    # EU-02: 14 tài khoản — đúng 2 lãnh đạo nghiệp vụ ở phường A (leader.config/
    # leader.approve chỉ dùng trong fixtures/test, không seed lên DB demo).
    assert User.objects.count() == 14 and WorkRecord.objects.count() == 5
    assert all("giả lập" in u.full_name for u in User.objects.all())
    assert all("giả lập" in u.unit.name for u in User.objects.all())
    # STT8/STT9: 5 tổ + 2 lãnh đạo + 5 cán bộ ở phường A
    ua = Unit.objects.get(name__contains="phường A")
    assert Department.objects.filter(unit=ua).count() == 5
    assert User.objects.filter(unit=ua, role="LEADER").count() == 2
    assert User.objects.filter(unit=ua, role="OFFICER").count() == 5
    pws = [line.split("\t")[1] for line in cred.read_text().splitlines()]
    assert len(set(pws)) == 14 and all(len(p) >= 16 for p in pws)
    assert oct(cred.stat().st_mode & 0o777) == "0o600"
    call_command("seed_demo", credentials_file=str(cred))  # idempotent: no dupes, no error
    assert User.objects.count() == 14 and WorkRecord.objects.count() == 5
    overdue = WorkRecord.objects.get(reference_no="GL-002/2026")
    assert overdue.notifications.filter(type="OVERDUE").exists()


def test_demo_settings_secure(monkeypatch):
    import importlib

    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "demo.invalid")
    monkeypatch.setenv("POSTGRES_PASSWORD", "y")
    demo = importlib.import_module("config.settings.demo")
    assert demo.DEBUG is False
    assert demo.SESSION_COOKIE_SECURE and demo.CSRF_COOKIE_SECURE
    assert demo.SECURE_SSL_REDIRECT
