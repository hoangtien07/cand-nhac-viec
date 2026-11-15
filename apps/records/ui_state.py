"""UI view-state (not authorization): the 'năm làm việc' filter.

ASSUMPTION (DESIGN_SPEC §2.3): work year = year of WorkRecord.created_at in Asia/Ho_Chi_Minh.
Callers must pass an already permission-scoped queryset.
"""

import datetime
import re

from django.utils import timezone

from .timeutils import VN_TZ

SESSION_KEY = "pocketops_work_year"
YEARS_BACK = 5
YEARS_AHEAD = 1


def current_work_year(now=None):
    return (now or timezone.now()).astimezone(VN_TZ).year


def work_year_choices(now=None):
    year = current_work_year(now)
    return range(year - YEARS_BACK, year + YEARS_AHEAD + 1)


def parse_work_year(value, now=None):
    """Strict: exactly 4 ASCII digits inside the allowed window, else None."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}", value):
        return None
    year = int(value)
    return year if year in work_year_choices(now) else None


def get_active_work_year(request):
    stored = request.session.get(SESSION_KEY)
    if isinstance(stored, int) and stored in work_year_choices():
        return stored
    return current_work_year()


def work_year_bounds(year):
    start = datetime.datetime(year, 1, 1, tzinfo=VN_TZ)
    return start, datetime.datetime(year + 1, 1, 1, tzinfo=VN_TZ)


def filter_created_in_work_year(qs, year):
    start, end = work_year_bounds(year)
    return qs.filter(created_at__gte=start, created_at__lt=end)
