import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection

VN_TZ = ZoneInfo(settings.TIME_ZONE)


def db_now():
    """Authoritative 'now' from the PostgreSQL clock (never from the browser)."""
    with connection.cursor() as cur:
        cur.execute("SELECT statement_timestamp()")
        return cur.fetchone()[0]


def local_date(dt):
    return dt.astimezone(VN_TZ).date()


def due_at_for_date(day):
    """ASSUMPTION H04: a deadline date expires at 23:59:59 Vietnam time."""
    h, m, s = settings.POCKETOPS_DUE_TIME
    return datetime.datetime.combine(day, datetime.time(h, m, s), tzinfo=VN_TZ)
