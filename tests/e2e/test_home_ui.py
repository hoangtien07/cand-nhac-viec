"""Home redesign: layout, navigation, filters, year selector, a11y smoke on 3 viewports (read-only)."""

import re

import pytest

from .conftest import BASE, OUT

pytestmark = pytest.mark.e2e

VIEWPORTS = {"1672x941": (1672, 941), "1280x900": (1280, 900), "390x844": (390, 844)}

UNLABELLED_JS = """() => [
  ...document.querySelectorAll('input:not([type=hidden]), select, textarea, button, a[href]')]
  .filter(el => el.checkVisibility({visibilityProperty: true}))
  .filter(el => {
    if (el.getAttribute('aria-label')) return false;
    if (el.tagName === 'A' || el.tagName === 'BUTTON') return !el.textContent.trim();
    return !((el.id && document.querySelector(`label[for="${el.id}"]`)) || el.closest('label'));
  }).map(el => el.outerHTML.slice(0, 120))"""


@pytest.mark.parametrize("size", list(VIEWPORTS), ids=list(VIEWPORTS))
def test_home_layout_and_a11y(login, size):
    from playwright.sync_api import expect

    w, h = VIEWPORTS[size]
    page = login({"width": w, "height": h})
    OUT.mkdir(parents=True, exist_ok=True)
    assert page.get_by_test_id("app-header").count() == 1
    assert page.get_by_test_id("app-sidebar").count() == 1
    expect(page.get_by_role("heading", level=1)).to_contain_text("Xin chào")
    for hook in ("overdue", "soon", "processing", "done"):
        expect(page.get_by_test_id(f"dashboard-kpi-{hook}")).to_be_visible()
    expect(page.get_by_test_id("dashboard-filters")).to_be_visible()
    expect(page.get_by_test_id("dashboard-calendar")).to_be_visible()
    expect(page.get_by_test_id("footer-work-year")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= w, "horizontal page overflow"
    assert page.evaluate(UNLABELLED_JS) == []
    page.screenshot(path=OUT / f"home-{size}.png")
    page.screenshot(path=OUT / f"home-{size}-full.png", full_page=True)

    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Bỏ qua tới nội dung"
    page.keyboard.press(
        "Tab"
    )  # focus order: skip link -> header (menu toggle on small screens, brand otherwise)
    if w < 1024:
        expect(page.get_by_role("button", name="Mở menu")).to_be_focused()
    else:
        assert page.evaluate("document.activeElement.classList.contains('po-brand')")

    if w < 1024:
        sidebar = page.get_by_test_id("app-sidebar")
        expect(sidebar).to_be_hidden()
        toggle = page.get_by_role("button", name="Mở menu")
        toggle.click()
        expect(sidebar).to_be_visible()
        expect(page.get_by_role("link", name="Trang chủ")).to_be_focused()
        page.keyboard.press("Escape")
        expect(sidebar).to_be_hidden()
        expect(page.get_by_role("button", name="Mở menu")).to_be_focused()
        assert toggle.get_attribute("aria-expanded") == "false"
    else:
        expect(page.get_by_role("link", name="Trang chủ")).to_have_attribute("aria-current", "page")


def test_tabs_search_history_and_year(login):
    from playwright.sync_api import expect

    page = login({"width": 1280, "height": 900})
    page.get_by_test_id("dashboard-tab-due_soon").click()
    expect(page).to_have_url(re.compile(r"tab=due_soon"))
    expect(page.get_by_test_id("dashboard-tab-due_soon")).to_have_attribute("aria-current", "true")
    page.reload()
    expect(page.get_by_test_id("dashboard-tab-due_soon")).to_have_attribute("aria-current", "true")

    page.get_by_label("Tìm theo số hiệu gốc hoặc số hiệu kết quả").fill("khong-ton-tai")
    page.get_by_role("button", name="Tìm").click()
    expect(page).to_have_url(re.compile(r"tab=due_soon.*q=khong-ton-tai|q=khong-ton-tai.*tab=due_soon"))
    expect(page.get_by_test_id("dashboard-empty")).to_be_visible()
    page.go_back()
    expect(page).not_to_have_url(re.compile(r"q="))
    expect(page.get_by_test_id("dashboard-tab-due_soon")).to_have_attribute("aria-current", "true")

    page.goto(f"{BASE}/")
    before = page.get_by_test_id("record-row").count()
    year = int(page.get_by_label("Năm làm việc:").input_value())
    page.get_by_label("Năm làm việc:").select_option(str(year - 1))
    page.get_by_role("button", name="Áp dụng").click()
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    expect(page.get_by_text(f"năm làm việc {year - 1}")).to_be_visible()
    assert page.get_by_test_id("record-row").count() == 0
    page.screenshot(path=OUT / "home-year-filter.png")
    page.get_by_label("Năm làm việc:").select_option(str(year))
    page.get_by_role("button", name="Áp dụng").click()
    expect(page.get_by_text(f"năm làm việc {year}")).to_be_visible()
    assert page.get_by_test_id("record-row").count() == before
