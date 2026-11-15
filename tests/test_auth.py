"""A01 login/logout, brute-force lockout, CSRF, login-required."""

import pytest
from django.test import Client

from .conftest import PW

pytestmark = pytest.mark.django_db


def test_login_ok_opens_dashboard_and_logout_kills_session(org):
    c = Client(HTTP_HOST="localhost")
    r = c.post("/login/", {"username": "o1", "password": PW})
    assert r.status_code == 302 and r["Location"] == "/"
    assert "Việc của tôi" in c.get("/").content.decode()
    r = c.post("/logout/")
    assert r.status_code == 302
    assert c.get("/").status_code == 302  # back to login


def test_wrong_password_and_unknown_user_give_same_generic_error(org):
    c = Client(HTTP_HOST="localhost")
    a = c.post("/login/", {"username": "o1", "password": "sai"}).content.decode()
    b = c.post("/login/", {"username": "khong-ton-tai", "password": "sai"}).content.decode()
    assert "Tên đăng nhập hoặc mật khẩu không đúng" in a
    assert "Tên đăng nhập hoặc mật khẩu không đúng" in b


def test_bruteforce_lockout(org):
    c = Client(HTTP_HOST="localhost")
    for _ in range(5):
        c.post("/login/", {"username": "o1", "password": "sai"})
    r = c.post("/login/", {"username": "o1", "password": PW})
    assert r.status_code == 429
    assert "Tạm khóa" in r.content.decode()


def test_anonymous_redirected_to_login(org):
    c = Client(HTTP_HOST="localhost")
    for url in ["/", "/ho-so/", "/thong-bao/", "/bao-cao/", "/quan-tri/"]:
        r = c.get(url)
        assert r.status_code == 302 and r["Location"].startswith("/login/"), url


def test_mutations_require_csrf(org):
    from .conftest import make_record

    rec = make_record(org.o1, org.d1, [org.o1])
    c = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    c.force_login(org.o1)
    r = c.post(f"/ho-so/{rec.pk}/nop/", {"code": "KQ-1", "confirm": "1"})
    assert r.status_code == 403
    rec.refresh_from_db()
    assert rec.status == "OPEN"


def test_logout_get_not_allowed(org):
    c = Client(HTTP_HOST="localhost")
    c.force_login(org.o1)
    assert c.get("/logout/").status_code == 405
