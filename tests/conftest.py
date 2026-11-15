import datetime
from types import SimpleNamespace

import pytest
from django.test import Client

from apps.accounts.models import Role, User
from apps.organization.models import Department, Unit
from apps.records import services
from apps.records.timeutils import db_now, local_date

PW = "synthetic-test-pw-1"


def _org():
    ua, ub = Unit.objects.create(name="Đơn vị Test A"), Unit.objects.create(name="Đơn vị Test B")
    d1 = Department.objects.create(unit=ua, name="Phòng 1")
    d2 = Department.objects.create(unit=ua, name="Phòng 2")
    d3 = Department.objects.create(unit=ub, name="Phòng 3")
    spec = {
        "admin": (ua, None, Role.SYS_ADMIN),
        "leader": (ua, d1, Role.LEADER),
        "mgr1": (ua, d1, Role.DEPT_MANAGER),
        "mgr2": (ua, d2, Role.DEPT_MANAGER),
        "o1": (ua, d1, Role.OFFICER),
        "o1b": (ua, d1, Role.OFFICER),
        "o1c": (ua, d1, Role.OFFICER),
        "o2": (ua, d2, Role.OFFICER),
        "o2b": (ua, d2, Role.OFFICER),
        "bleader": (ub, d3, Role.LEADER),
        "b1": (ub, d3, Role.OFFICER),
    }
    users = {}
    for name, (unit, dept, role) in spec.items():
        u = User(username=name, full_name=f"Người test {name}", unit=unit, department=dept, role=role)
        u.set_password(PW)
        u.save()
        users[name] = u
    for d, m in ((d1, "mgr1"), (d2, "mgr2")):
        d.manager = users[m]
        d.save()
    return SimpleNamespace(ua=ua, ub=ub, d1=d1, d2=d2, d3=d3, **users)


@pytest.fixture
def org(db):
    return _org()


@pytest.fixture
def org_tx(transactional_db):
    return _org()


def today():
    return local_date(db_now())


def make_record(actor, dept, assignees, watchers=(), ref="TEST-001", days=3):
    return services.create_record(
        actor,
        reference_no=ref,
        owner_department=dept,
        due_date=today() + datetime.timedelta(days=days),
        assignees=assignees,
        watchers=watchers,
    )


@pytest.fixture
def client_for():
    def make(user):
        c = Client(HTTP_HOST="localhost")
        c.force_login(user)
        return c

    return make
