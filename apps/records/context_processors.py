"""Lightweight shell context (header/sidebar/footer). No business-record queries here."""

import re

from . import policies
from .ui_state import get_active_work_year, work_year_choices

_NAV = {
    "dashboard": "home",
    "records:create": "create",
    "records": "records",
    "folders": "folders",
    "reports": "reports",
    "notifications": "notifications",
    "adminpanel": "admin",
}


def initials(full_name):
    words = [w for w in re.sub(r"\(.*?\)", " ", full_name or "").split() if w[:1].isalpha()]
    if not words:
        return "?"
    picked = words[0][0] + (words[-1][0] if len(words) > 1 else "")
    return picked.upper()


def _nav_key(request):
    match = getattr(request, "resolver_match", None)
    if not match:
        return ""
    for key in (match.view_name, match.namespace):
        if key in _NAV:
            return _NAV[key]
    return ""


def ui_shell(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    nav_key = _nav_key(request)
    year_ctx = {}
    if user.is_business_user:
        year_ctx = {
            "active_work_year": get_active_work_year(request),
            "work_year_choices": work_year_choices(),
        }
    unit_name = user.unit.name if user.unit_id else ""
    return {
        "current_user_initials": initials(user.full_name),
        "current_department_label": user.department.name if user.department_id else unit_name,
        "current_unit_label": unit_name,
        "can_create_record": user.is_business_user and policies.creatable_departments(user).exists(),
        **{f"nav_is_{k}": nav_key == k for k in set(_NAV.values())},
        **year_ctx,
    }
