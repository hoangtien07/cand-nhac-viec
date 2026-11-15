import re

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _html(client, url="/"):
    resp = client.get(url, follow=True)
    assert resp.status_code == 200
    return resp.content.decode()


def test_business_shell_has_one_header_one_sidebar(org, client_for):
    body = _html(client_for(org.o1))
    for hook in ("app-header", "app-sidebar", "app-footer", "current-user-menu"):
        assert body.count(f'data-testid="{hook}"') == 1, hook
    assert org.o1.full_name in body
    assert org.d1.name in body


def test_home_nav_item_is_active_on_dashboard(org, client_for):
    body = _html(client_for(org.o1))
    active = re.findall(r'<a[^>]*aria-current="page"[^>]*>', body)
    assert len(active) == 1
    assert f'href="{reverse("dashboard")}"' in active[0]


def test_sysadmin_cannot_see_business_nav(org, client_for):
    body = _html(client_for(org.admin), reverse("adminpanel:home"))
    sidebar = body.split('data-testid="app-sidebar"', 1)[1].split("</nav>", 1)[0]
    for name in ("records:list", "records:create", "reports:report", "notifications:inbox"):
        assert f'href="{reverse(name)}"' not in sidebar, name
    assert f'href="{reverse("adminpanel:home")}' in sidebar


@pytest.mark.parametrize("who", ["leader", "mgr1", "o1"])
def test_admin_nav_is_role_bound(org, client_for, who):
    body = _html(client_for(getattr(org, who)))
    assert reverse("adminpanel:home") not in body
    assert "Cấu hình hệ thống" not in body
    assert "Vai trò &amp; quyền" not in body


def test_anonymous_login_keeps_standalone_layout(db):
    body = Client(HTTP_HOST="localhost").get(reverse("accounts:login")).content.decode()
    assert 'data-testid="app-header"' not in body
    assert 'data-testid="app-sidebar"' not in body
    assert "Đăng nhập PocketOps" in body


def test_logout_form_is_post_with_csrf(org, client_for):
    body = _html(client_for(org.o1))
    menu = body.split('data-testid="current-user-menu"', 1)[1]
    logout = reverse("accounts:logout")
    form = re.search(rf'<form[^>]*action="{logout}"[^>]*>(.*?)</form>', menu, re.S)
    assert form and 'method="post"' in form.group(0)
    assert "csrfmiddlewaretoken" in form.group(1)


def test_unread_badge_comes_from_query(org, client_for):
    body = _html(client_for(org.o1))
    assert 'data-testid="header-unread"' not in body  # no notifications yet → no fake badge


def test_static_assets_are_same_origin(org, client_for):
    body = _html(client_for(org.o1))
    assert not re.search(r'(src|href)="(https?:)?//', body)
