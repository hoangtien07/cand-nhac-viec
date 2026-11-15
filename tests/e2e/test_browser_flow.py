"""A28: real browser against a running stack (docker compose). Skipped unless E2E_BASE_URL is set.

Mutates demo data (closes one OPEN record of E2E_USER per viewport). Run on a freshly seeded demo DB.
"""

import re

import pytest

from .conftest import BASE, OUT

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"]
)
def test_login_my_work_submit_done(login, viewport):
    from playwright.sync_api import expect

    OUT.mkdir(parents=True, exist_ok=True)
    tag = "desktop" if viewport["width"] > 800 else "mobile"
    page = login(viewport)
    expect(page.get_by_role("heading", name="Công việc của tôi")).to_be_visible()
    page.screenshot(path=OUT / f"1-dashboard-{tag}.png", full_page=True)

    row = page.get_by_test_id("record-row").filter(has_not_text="Đã hoàn thành").first
    ref = row.get_attribute("data-reference")
    row.get_by_role("link", name=ref).click()
    expect(page.get_by_role("heading", name=f"Hồ sơ {ref}")).to_be_visible()
    code = f"KQ-E2E-{tag.upper()}"
    page.get_by_role("textbox", name="Số hiệu kết quả").fill(code)
    page.get_by_role("button", name="Tiếp tục").click()
    expect(page.get_by_role("heading", name="Xác nhận nộp số hiệu")).to_be_visible()
    page.screenshot(path=OUT / f"2-confirm-{tag}.png", full_page=True)
    page.get_by_role("button", name="Xác nhận nộp").click()
    expect(page.get_by_text(re.compile("Hồ sơ đã HOÀN THÀNH"))).to_be_visible()
    expect(page.locator(".badge-done").first).to_contain_text("Đã hoàn thành")
    expect(page.get_by_text(code, exact=True)).to_be_visible()
    page.screenshot(path=OUT / f"3-done-{tag}.png", full_page=True)

    page.goto(f"{BASE}/")
    done_row = page.locator(f'[data-testid="record-row"][data-reference="{ref}"]')
    expect(done_row).to_contain_text("Đã hoàn thành")

    page.get_by_test_id("current-user-menu").locator("summary").click()
    page.get_by_role("button", name="Đăng xuất").click()
    expect(page.get_by_role("heading", name="Đăng nhập PocketOps")).to_be_visible()
