"""A28: real browser against a running stack (docker compose). Skipped unless E2E_BASE_URL is set.

Mutates demo data (closes one OPEN record of E2E_USER). Run on a freshly seeded demo DB.
"""

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

BASE = os.environ.get("E2E_BASE_URL")
OUT = Path(os.environ.get("E2E_SCREENSHOT_DIR", "var/e2e"))


@pytest.fixture(scope="module")
def browser():
    if not BASE:
        pytest.skip("E2E_BASE_URL not set")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"]
)
def test_login_my_work_submit_done(browser, viewport):
    from playwright.sync_api import expect

    OUT.mkdir(parents=True, exist_ok=True)
    tag = "desktop" if viewport["width"] > 800 else "mobile"
    ctx = browser.new_context(viewport=viewport, ignore_https_errors=True, locale="vi-VN")
    page = ctx.new_page()
    page.goto(f"{BASE}/login/")
    page.get_by_label("Tên đăng nhập").fill(os.environ["E2E_USER"])
    page.get_by_label("Mật khẩu").fill(os.environ["E2E_PASSWORD"])
    page.get_by_role("button", name="Đăng nhập").click()
    expect(page.get_by_role("heading", name="Việc của tôi")).to_be_visible()
    page.screenshot(path=OUT / f"1-dashboard-{tag}.png", full_page=True)

    row = page.locator("section a", has=page.locator("text=Đang xử lý")).first
    if not row.count():
        row = page.locator("section a", has=page.locator(".badge-overdue, .badge-soon")).first
    ref = row.locator("span.font-semibold").inner_text()
    row.click()
    expect(page.get_by_role("heading", name=f"Hồ sơ {ref}")).to_be_visible()
    code = f"KQ-E2E-{tag.upper()}"
    page.get_by_role("textbox", name="Số hiệu kết quả").fill(code)
    page.get_by_role("button", name="Tiếp tục").click()
    expect(page.get_by_role("heading", name="Xác nhận nộp số hiệu")).to_be_visible()
    page.screenshot(path=OUT / f"2-confirm-{tag}.png", full_page=True)
    page.get_by_role("button", name="Xác nhận nộp").click()
    expect(page.get_by_text(re.compile("Hồ sơ đã HOÀN THÀNH"))).to_be_visible()
    expect(page.locator("h1 + .badge-done, .badge-done").first).to_have_text("Đã hoàn thành")
    expect(page.get_by_text(code, exact=True)).to_be_visible()
    page.screenshot(path=OUT / f"3-done-{tag}.png", full_page=True)

    page.get_by_role("button", name="Đăng xuất").click()
    expect(page.get_by_role("heading", name="Đăng nhập PocketOps")).to_be_visible()
    ctx.close()
