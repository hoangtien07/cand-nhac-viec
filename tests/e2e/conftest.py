import os
from pathlib import Path

import pytest

BASE = os.environ.get("E2E_BASE_URL")
OUT = Path(os.environ.get("E2E_SCREENSHOT_DIR", "var/e2e"))


@pytest.fixture(scope="session")
def browser():
    if not BASE:
        pytest.skip("E2E_BASE_URL not set")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def login(browser):
    """Return a logged-in page factory; contexts are closed after the test."""
    contexts = []

    def make(viewport):
        from playwright.sync_api import expect

        ctx = browser.new_context(viewport=viewport, ignore_https_errors=True, locale="vi-VN")
        contexts.append(ctx)
        page = ctx.new_page()
        page.goto(f"{BASE}/login/")
        page.get_by_label("Tên đăng nhập").fill(os.environ["E2E_USER"])
        page.get_by_label("Mật khẩu").fill(os.environ["E2E_PASSWORD"])
        page.get_by_role("button", name="Đăng nhập").click()
        expect(page.get_by_test_id("dashboard-records")).to_be_visible()
        return page

    yield make
    for ctx in contexts:
        ctx.close()
