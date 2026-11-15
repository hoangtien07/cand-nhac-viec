"""Owner feedback 2026-11-15: profile page + notifications only in the header dropdown."""

import datetime

import pytest
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.notifications.models import Notification
from apps.notifications.services import remind_record
from apps.records.timeutils import VN_TZ

from .conftest import PW, make_record, today

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


def _notify(org):
    rec = make_record(org.leader, org.d1, [org.o1, org.o1b], ref="NOTI-1", days=1)
    remind_record(rec.pk, now=datetime.datetime.combine(today(), datetime.time(10), tzinfo=VN_TZ))
    return rec


@pytest.mark.parametrize("who", ["o1", "leader", "admin"])
def test_profile_is_linked_and_read_only(org, client_for, who):
    user = getattr(org, who)
    c = client_for(user)
    home = c.get("/", follow=True).content.decode()
    menu = home.split('data-testid="current-user-menu"', 1)[1]
    assert f'href="{reverse("accounts:profile")}"' in menu
    resp = c.get(reverse("accounts:profile"))
    body = resp.content.decode()
    assert resp.status_code == 200 and user.username in body and user.get_role_display() in body
    info = body.split('data-testid="profile-info"', 1)[1].split("</dl>", 1)[0]
    assert "<input" not in info and "<select" not in info
    assert c.post(reverse("accounts:profile"), {"role": "LEADER"}).status_code == 405


def test_password_change_self_service(org, client_for):
    c = client_for(org.o1)
    url = reverse("accounts:password_change")
    bad = c.post(
        url, {"old_password": "wrong", "new_password1": "Mk-moi-2026-xyz", "new_password2": "Mk-moi-2026-xyz"}
    )
    assert bad.status_code == 200
    ok = c.post(
        url, {"old_password": PW, "new_password1": "Mk-moi-2026-xyz", "new_password2": "Mk-moi-2026-xyz"}
    )
    assert ok.status_code == 302 and ok["Location"] == reverse("accounts:profile")
    assert c.get("/").status_code == 200  # session kept
    org.o1.refresh_from_db()
    assert org.o1.check_password("Mk-moi-2026-xyz") and org.o1.role == "OFFICER"
    ev = AuditEvent.objects.get(actor=org.o1, action="user.changed")
    assert ev.metadata == {"user": str(org.o1.pk), "change": "password_self_service"}
    strict = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
    strict.force_login(org.o1b)
    assert (
        strict.post(url, {"old_password": PW, "new_password1": "x", "new_password2": "x"}).status_code == 403
    )


def test_notifications_page_removed_from_nav_and_quick_actions(org, client_for):
    c = client_for(org.o1)
    resp = c.get("/")
    sidebar = resp.content.decode().split('data-testid="app-sidebar"', 1)[1].split("</nav>", 1)[0]
    assert reverse("notifications:inbox") not in sidebar
    assert "Thông báo" not in [a["label"] for a in resp.context["quick_actions"]]
    plain = c.get(reverse("notifications:inbox"))
    assert plain.status_code == 302 and plain["Location"] == reverse("dashboard") + "?notif=open"


def test_header_dropdown_is_recipient_only(org, client_for):
    rec = _notify(org)
    body = client_for(org.o1).get(reverse("notifications:inbox"), headers=HX).content.decode()
    assert 'data-testid="app-header"' not in body
    assert body.count('data-testid="notification-item"') == 1 and rec.reference_no in body
    assert (
        'data-testid="notification-item"'
        not in client_for(org.o2).get(reverse("notifications:inbox"), headers=HX).content.decode()
    )
    nojs = client_for(org.o1).get("/?notif=open").content.decode()
    header = nojs.split('data-testid="header-notifications"', 1)[1].split("</details>", 1)[0]
    assert header.startswith(" open>")
    assert rec.reference_no in header


def test_mark_read_updates_badge_out_of_band(org, client_for):
    _notify(org)
    c = client_for(org.o1)
    assert 'data-testid="header-unread"' in c.get("/").content.decode()
    n = Notification.objects.get(recipient=org.o1)
    resp = c.post(reverse("notifications:mark_read", args=[n.pk]), headers=HX).content.decode()
    assert 'hx-swap-oob="true"' in resp and 'data-testid="header-unread"' not in resp
    assert client_for(org.o1b).post(reverse("notifications:mark_read", args=[n.pk])).status_code == 404
    resp = c.post(reverse("notifications:mark_all_read"), headers=HX).content.decode()
    assert "Thông báo nhắc hạn" in resp and 'hx-swap-oob="true"' in resp
