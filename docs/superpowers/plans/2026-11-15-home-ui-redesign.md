# CAND PocketOps Home UI & Shared Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triển khai trang chủ CAND PocketOps khớp ảnh được chủ dự án duyệt, tạo shared design system cho Django Templates/HTMX, giữ nguyên nghiệp vụ và bảo mật đã nghiệm thu.

**Architecture:** Refactor trên repo hiện có, **không rewrite**. Shell/partials UI trên `templates/base.html`; Tailwind v4 và SVG local; view/query presentation layer lấy dữ liệu từ `policies.visible_records_queryset` và `notifications.queries`. Bộ lọc năm hiển thị lưu trong session và thực thi qua phạm vi `created_at` (không thêm schema trong bản này).

**Tech Stack:** Python 3.12, Django 5.2 LTS, Django Templates, HTMX 2.x, Tailwind v4 (CLI hiện tại), PostgreSQL 16+, pytest-django, Playwright; **không thêm React/SPA/CDN**.

**Spec:** `DESIGN_SPEC.md` và `reference/home-approved.png` (nằm cùng gói này); nguồn nghiệp vụ trong repo `AGENTS.md`, `CONTEXT.md`, `ARCHITECTURE.md`, `ACCEPTANCE.md`.

**Repo baseline:** `hoangtien07/cand-nhac-viec` branch `main`, commit `3b183d3e7a901a3cf84a239728094c05e540fbc7` (15/11/2026); recheck HEAD trước khi triển khai.

## Global Constraints

- **Một hồ sơ = một công việc**, không có task con, không upload/nội dung nhạy cảm. `WorkRecord` hiện **không có trích yếu**: KHÔNG thêm trường hoặc hardcode mô tả chỉ vì ảnh.
- `records.dashboard` và `records.list` chỉ truy cập qua policy cũ; admin kỹ thuật không được đọc record nghiệp vụ. Chỉ hiển thị menu kỹ thuật nếu role thực sự được phép.
- `work_year`: năm `WorkRecord.created_at` theo `Asia/Ho_Chi_Minh`, session preference. Không dùng năm trong `reference_no`. Không đổi `User.unit`/`department` từ footer.
- `deadline_state` là **derived** bằng logic `apps/records/queries.py`, `OPEN`/`DONE` không đổi. Đừng làm sai `submit_result_reference` hay lịch nhắc hạn hiện có.
- Không dùng CDN hay dữ liệu/hệ thống thật; logo chính thức chỉ sử dụng khi có quyền. Demo banner giữ trên mọi trang.
- HTML escaped, CSRF nguyên vẹn, Django POST logout giữ nguyên; responsive không tạo overflow body.
- Giữ CSS build đang có: `npm ci && npm run build:css`; không tự thêm UI framework mới trước khi chứng minh nhu cầu.
- Từng task phải có test → FAIL trước → sửa tối thiểu → PASS → commit; giữ các regression tests đang tồn tại.

## Review Focus

1. **Dữ liệu chéo đơn vị/người:** đổi tab/year/search không làm lộ hồ sơ không có quyền; test `test_dashboard_respects_policy_under_year_and_search` trong Task 3.
2. **Năm làm việc và ngày biên:** hồ sơ tạo lúc 31/12/2026 23:59 VN vs 01/01/2027 00:00 VN phải tách đúng năm; test `test_work_year_vietnam_midnight_boundary` trong Task 2.
3. **DONE nhưng hạn đã qua:** record DONE không được KPI overdue/reminder pending; test `test_done_never_in_overdue` trong Task 3/5.
4. **HTMX và history:** filter/next/back không mất `q/tab/year`; test `test_dashboard_filter_preserves_state` trong Task 3, E2E Task 7.
5. **Role UX và keyboard:** leader không tự có sys-admin; officer thấy link có quyền; mobile menu/tab/dropdown/submit chạy keyboard; tests `test_admin_nav_is_role_bound`, `test_mobile_navigation_and_focus` Task 1/7.

---

## 0. File map và trách nhiệm (tối thiểu, có thể gộp nếu không làm mất ranh giới)

| Path | Trách nhiệm / tác động |
|---|---|
| `assets/app.css` **Modify** | Tailwind v4 tokens + UI classes + responsive/focus |
| `templates/base.html` **Modify** | Shell grid/header/left sidebar/content/footer; giữ login layout không bị áp shell |
| `templates/components/_header.html` **Create** | Brand, notifications, user menu, help; logout POST |
| `templates/components/_sidebar.html` **Create** | Role-aware navigation, active state |
| `templates/components/_footer.html` **Create** | Department/unit read-only + year selector thật + demo disclaimer |
| `templates/components/_messages.html` **Create** | Django messages reusable |
| `static/icons/pocketops.svg` **Create** | Same-origin icons, no CDN |
| `templates/components/_kpi_card.html` **Create** | KPI link/card |
| `templates/components/_filter_bar.html` **Create** | Search and filter gần bảng |
| `templates/components/_record_table.html` **Create** | Table dashboard, semantic HTML |
| `templates/components/_pagination.html` **Create** | Query state-safe links |
| `templates/components/_calendar.html` **Create** | Lịch tháng hiển thị kỳ hạn đúng scope |
| `templates/components/_reminder_list.html` **Create** | 3 actionable notifications recipient-only |
| `templates/components/_quick_actions.html` **Create** | Shortcut theo role/capability |
| `templates/records/dashboard.html` **Rewrite** | Kết hợp shared components theo ảnh tham chiếu |
| `apps/records/ui_state.py` **Create** | Year selection, bounds, calendar month / query state |
| `apps/records/dashboard_queries.py` **Create** | Dashboard dataset / counts / filters / calendar records |
| `apps/records/context_processors.py` **Create** | Sidebar/footer context nhẹ, user info + work_year; không query nặng |
| `apps/records/views.py` **Modify** | Dashboard GET, year POST, optional shared list filter |
| `apps/records/urls.py` **Modify** | Named `records:set_work_year` route |
| `config/settings/base.py` **Modify** | Add UI context processor (no middleware new) |
| `apps/reports/views.py` **Modify** | Year-aware reports (giữ backward compatible signature) |
| `templates/records/list.html`, `templates/records/_list_table.html` **Minor Modify** | Shared filter/badge/pagination theo shell và year |
| `tests/test_work_year.py` **Create** | Year validation/filter/date boundary |
| `tests/test_dashboard_ui.py` **Create** | KPI, scope, tabs, search, calendar, reminders |
| `tests/test_navigation_ui.py` **Create** | Shell nav/sidebar/header/footer permissions |
| `tests/e2e/test_browser_flow.py` **Modify** | Stable selectors sau refactor, giữ submit-result smoke |
| `tests/e2e/test_home_ui.py` **Create** | 3 viewports, navigation, visual screenshot |

**Chú ý:** Không chỉnh `apps/records/models.py`, migrations, `apps/records/services.py`, `apps/records/policies.py`, `apps/notifications/services.py` trừ khi phát hiện lỗi độc lập và được chủ dự án phê duyệt scope change.

### Task 1: App shell, header, sidebar và footer tĩnh

**Files:** `templates/base.html`, `templates/components/_header.html`, `_sidebar.html`, `_footer.html`, `_messages.html`, `assets/app.css`, `static/icons/pocketops.svg`, `tests/test_navigation_ui.py`.

**Interfaces:** Consumes `request.user`, `user.is_business_user`, `user.is_sys_admin`, `unread_notifications` (context processor đã có), existing URL names (`dashboard`, `records:list`, `records:create`, `notifications:inbox`, `reports:report`, `adminpanel:home`, `accounts:logout`). Produces shared HTML hooks `data-testid="app-header"`, `app-sidebar`, `app-footer`, `current-user-menu`; `content` block unchanged.

- [ ] Step 1 — Test FAIL: tạo `test_business_shell_has_one_header_one_sidebar`, `test_sysadmin_cannot_see_business_nav`, `test_admin_nav_is_role_bound`, `test_anonymous_login_keeps_standalone_layout`, `test_logout_form_is_post_with_csrf`. Run `uv run pytest tests/test_navigation_ui.py -q`, expected FAIL trước code.
- [ ] Step 2 — Implement shell desktop: header `72px`, left sidebar `272px`, main flex, footer `56px`; sidebar ẩn/thu gọn ở viewport nhỏ; thông báo badge và tên user từ backend; footer giai đoạn này hiển thị đơn vị read-only, year placeholder được thay bằng form thật Task 2.
- [ ] Step 3 — Dùng CSS token trong `assets/app.css`; icon SVG same-origin; class rõ `po-app-shell`, `po-header`, `po-sidebar`, `po-main`, `po-footer`; giữ `.btn-primary`, `.input`, `.badge-*` để không phá các form/template cũ.
- [ ] Step 4 — Build CSS + tests: `npm ci && npm run build:css`, `uv run pytest tests/test_navigation_ui.py tests/test_auth.py -q`. Expected PASS. Manual desktop/mobile shell và login visual smoke.
- [ ] Step 5 — Commit `feat(ui): introduce PocketOps shared application shell`.

### Task 2: Bộ lọc năm làm việc thật ở footer (không đổi dữ liệu nghiệp vụ)

**Files:** `apps/records/ui_state.py`, `apps/records/context_processors.py`, `apps/records/views.py`, `apps/records/urls.py`, `config/settings/base.py`, `templates/components/_footer.html`, `tests/test_work_year.py`.

**Interfaces:**
- Produce `get_active_work_year(request: HttpRequest) -> int`: đọc session, fallback năm hiện tại theo VN timezone; invalid value fallback. Session key `pocketops_work_year`.
- Produce `filter_created_in_work_year(qs: QuerySet[WorkRecord], year: int) -> QuerySet[WorkRecord]`: filter `created_at >= start_of_year(VN)` và `< start_of_next_year(VN)`; **caller must provide permission-scoped qs**.
- Produce `set_work_year(request: HttpRequest) -> HttpResponse`: `@require_POST` + CSRF, year integer in `[current_year-5, current_year+1]`, save session then redirect `dashboard`; reject invalid year with 400 or user-visible error without changing current session.
- Route `path("nam-lam-viec/", views.set_work_year, name="set_work_year")` before `<uuid:pk>`.
- Context processor returns `active_work_year`, `work_year_choices`, `current_department_label`, `current_unit_label` with no business record count query.

- [ ] Step 1 — Tests FAIL: `test_work_year_default_is_local_year`, `test_work_year_vietnam_midnight_boundary`, `test_work_year_post_requires_csrf_and_valid_integer`, `test_year_switch_does_not_change_unit_or_department`, `test_year_selector_persists_in_session_across_navigation`.
- [ ] Step 2 — Implement `ui_state.py` with `zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")` and aware datetime bounds, no filename/year parsing. Use Django forms or explicit integer validation for POST, reject `2026abc`, `1900`, `9999`.
- [ ] Step 3 — Register context processor, add footer `<form method="post" action="{% url 'records:set_work_year' %}">`; `onchange` may auto-submit with accessible fallback `<button>Áp dụng</button>`. Unit text remains read-only.
- [ ] Step 4 — Tests + build: `uv run pytest tests/test_work_year.py tests/test_scope.py -q`. Expected PASS.
- [ ] Step 5 — Commit `feat(ui): make work-year footer selector functional`.

### Task 3: Dashboard data contract — KPI, tabs, search, list và pagination

**Files:** `apps/records/dashboard_queries.py`, `apps/records/views.py`, `templates/records/dashboard.html`, `templates/components/_kpi_card.html`, `_filter_bar.html`, `_record_table.html`, `_pagination.html`, `tests/test_dashboard_ui.py`.

**Interfaces:**
- Produce `get_dashboard_data(*, user: User, year: int, tab: str, q: str, page_number: str | None, now: datetime) -> dict`: returns `counts` keys `{all, overdue, due_soon, processing, done}`, `page`, `tab`, `q`, `can_create`. It must start with `policies.visible_records_queryset(user).filter(assignees__user=user, assignees__is_active=True).distinct()` then apply year filter.
- Produce `filter_dashboard_search(qs, q)` reusing code normalization/search by original and result number; no query of records outside outer scope.
- Tab values: `all|overdue|due_soon|processing|done`; invalid → `all` (without privilege change). Page length default `8` (or `10` if fit screenshot). Multiple assignees never duplicate same record.
- Widget hooks: `data-testid="dashboard-kpi-overdue|dashboard-kpi-soon|dashboard-kpi-processing|dashboard-kpi-done"`, `dashboard-tab-all`, `dashboard-filters`, `dashboard-records`, each row `data-testid="record-row"` + `data-reference="..."` for E2E.

- [ ] Step 1 — Tests FAIL: `test_dashboard_uses_assigned_work_only`, `test_dashboard_counts_partition_all_once`, `test_dashboard_respects_policy_under_year_and_search`, `test_done_never_in_overdue`, `test_dashboard_filter_preserves_state`, `test_dashboard_search_by_result_code_does_not_leak`, `test_invalid_tab_defaults_to_all`, `test_empty_dashboard_renders_actionable_empty_state`.
- [ ] Step 2 — Move query/pagination preparation into `dashboard_queries.py`; the view handles request + render. Use `apps.records.queries.overdue/due_soon/due_soon_cutoff` rather than redefining deadline thresholds.
- [ ] Step 3 — Render approved layout: greeting, 4 KPI, `Công việc của tôi` main card, 5 tabs, search/filter bar adjacent to table, semantic table; no fake `Trích yếu` text: **“Thông tin hồ sơ”** uses real `assigner`/reference metadata. All counts and tabs come from one scoped dataset.
- [ ] Step 4 — Implement query URL serialization preserving `tab/q/page`, use `request.GET.urlencode` (or a safe helper) rather than custom manual string concatenation. Maintain HTMX `hx-get`, `hx-target` and `hx-push-url` as progressive enhancement; normal GET must work with JS disabled.
- [ ] Step 5 — Build/test `uv run pytest tests/test_dashboard_ui.py tests/test_authz.py tests/test_records.py -q` and `npm run build:css`; expected PASS.
- [ ] Step 6 — Commit `feat(ui): build scoped home dashboard and task table`.

### Task 4: Right rail — lịch kỳ hạn và nhắc việc trong web

**Files:** `apps/records/dashboard_queries.py`, `apps/records/ui_state.py`, `apps/records/views.py`, `templates/components/_calendar.html`, `_reminder_list.html`, `templates/records/dashboard.html`, `tests/test_dashboard_ui.py`.

**Interfaces:**
- Extend `get_dashboard_data` return keys `calendar_weeks`, `calendar_label`, `calendar_month`, `reminders` and `reminder_count`.
- `calendar_weeks`: array of weeks containing day entries `{date, in_month, is_today, has_deadline, tone, href}`; DB queryset only uses year-filtered assigned records. Display current VN month (or same month of selected `year`). Month nav GET param `month=YYYY-MM` validated within work-year range.
- `reminders`: first 3 records from `notifications.queries.actionable(notifications.queries.visible_notifications(user))`, optionally filtered by `record.created_at` year; select_related for record; no scope inference from arbitrary notice IDs.

- [ ] Step 1 — Tests FAIL: `test_calendar_only_uses_visible_assigned_records`, `test_calendar_handles_month_turn_and_leap_year`, `test_reminder_list_is_recipient_only`, `test_done_notification_not_actionable`, `test_calendar_no_out_of_year_leak`.
- [ ] Step 2 — Implement calendar month view using Python standard `calendar` (Monday first), no new tables. Deadline highlights by status + legend text, click day may link to dashboard `?due_date=...` only if server supports the filter; otherwise **no dead-end link**.
- [ ] Step 3 — Implement `Nhắc việc hôm nay`/`Cần chú ý` panel: max 3 notifications, show type, ref, relative due/created time only if safe. Empty state factual; don't hardcode exactly 3.
- [ ] Step 4 — `uv run pytest tests/test_dashboard_ui.py tests/test_reminders.py -q`, expected PASS. Inspect SQL query count; avoid `N+1` in calendar and reminders.
- [ ] Step 5 — Commit `feat(ui): add scoped calendar and reminder rail`.

### Task 5: Quick actions + shared components roll-out (không làm lại mọi màn)

**Files:** `templates/components/_quick_actions.html`, `templates/components/_status_badge.html`, `templates/components/_empty_state.html`, `templates/components/_pagination.html`, `templates/records/dashboard.html`, `templates/records/list.html`, `templates/records/_list_table.html`, `templates/records/_state_badge.html`, `templates/notifications/inbox.html` (minor only), `apps/records/views.py`, `apps/reports/views.py`, `tests/test_navigation_ui.py`, `tests/test_work_year.py`, `tests/test_dashboard_ui.py`.

**Interfaces:** `quick_actions` entries `{label, icon, href, enabled}` from backend; permissions from existing `policies.creatable_departments(user)`, `policies.can_view_reports(user)`, `user.is_sys_admin`. Reuse old status logic as one source of truth; do not re-classify status differently in view/template. `Nộp kết quả` shortcut links to dashboard `?tab=processing` or `?tab=all` where user can pick a record, never executes submit itself.

- [ ] Step 1 — Tests FAIL: `test_quick_actions_hide_unauthorized_admin_and_create`, `test_status_badges_correct_in_list_and_dashboard`, `test_no_unimplemented_settings_links`, `test_shared_pagination_preserves_query_state`, `test_record_list_and_report_apply_same_work_year_scope`, `test_direct_record_detail_not_hidden_by_year`.
- [ ] Step 2 — Introduce tiny shared components, backfill `records.list` and notifications only as required for consistency. Avoid wholesale markup replacement of detail/create/report in this scope.
- [ ] Step 3 — Áp dụng `filter_created_in_work_year` **sau** policy filtering vào `record_list` trong `apps/records/views.py`. Với `apps/reports/views.py`, mở rộng `report_summary(user, now, year=None)` backward-compatible, lọc theo year nếu cung cấp; `report()` truyền `get_active_work_year(request)`. Do not conflate year filter with authorization; direct detail vẫn đọc theo policy. Thêm test đối chiếu cùng một bộ hồ sơ theo năm giữa dashboard/list/report.
- [ ] Step 4 — Ensure menu `Quản trị` is not visible to LEADER/DEPT_MANAGER/OFFICER unless existing backend route grants; no fake `role & permission` standalone screen if route does not exist.
- [ ] Step 5 — `uv run pytest tests/test_navigation_ui.py tests/test_work_year.py tests/test_dashboard_ui.py tests/test_records.py tests/test_authz.py -q`, expected PASS.
- [ ] Step 6 — Commit `refactor(ui): reuse status filters and capability-aware shortcuts`.

### Task 6: Shared CSS polish, accessibility, responsive 3 breakpoints

**Files:** `assets/app.css`, `templates/base.html`, shared components, `tests/test_navigation_ui.py`, `tests/e2e/test_home_ui.py`.

**Interfaces:** CSS tokens from `DESIGN_SPEC.md`; SVG local + focus states; desktop stable hooks unchanged.

- [ ] Step 1 — Write browser assertions (FAIL under unfinished UI): no page horizontal overflow at 1672×941, 1280×900, 390×844; sidebar toggle on mobile; focus order skip link → header/menu → main; badges distinguishable by text; no uncontrolled dropdown under keyboard.
- [ ] Step 2 — Implement `@layer components` system classes in `assets/app.css`, keep existing `.btn-primary`, `.input`, `.badge-*` aliases until all screens migrated; no FOUT CDN or inaccessible text.
- [ ] Step 3 — Responsive: ≥1440 3-column shell; 1024–1439 shrink sidebar/right rail; 768–1023 sidebar drawer + right rail below; ≤767 table scroll or row cards, working footer; `prefers-reduced-motion` no nonessential animation.
- [ ] Step 4 — Browser manual audit for screenshot at **1672×941** reference, plus 1280×900 and 390×844; record differences by regions (header, side, main, rail, footer). Use a11y browser tooling if installed; keyboard/contrast are acceptance gates.
- [ ] Step 5 — `npm run build:css && uv run pytest tests/test_navigation_ui.py -q`, expected PASS.
- [ ] Step 6 — Commit `style(ui): match approved home layout across viewports`.

### Task 7: Regression, E2E, screenshots, visual review

**Files:** `tests/e2e/test_browser_flow.py`, `tests/e2e/test_home_ui.py`, optionally `docs/UI_REDESIGN_ACCEPTANCE.md` (short; only evidence). No business service edits.

**Interfaces:** Playwright stable `data-testid` as specified above; full browser flow must continue to close record via existing two-step submit result and POST logout.

- [ ] Step 1 — Update old E2E selectors currently relying on `heading(name="Việc của tôi")` and `section a` + `span.font-semibold`, which become invalid under new markup; replace with stable `dashboard-records`/`record-row` and `get_by_role` selectors.
- [ ] Step 2 — Add `test_home_ui.py`: login; assert single header/sidebar, correct account, year in footer, KPI/table scope; change year→data changes; tab and search persist on reload/back; open record, submit result in detail via old two-step flow; desktop/mobile smoke.
- [ ] Step 3 — Run baseline and new suites on PostgreSQL (not SQLite):

```bash
npm ci && npm run build:css
uv run ruff check . && uv run ruff format --check .
uv run pytest -q -m "not e2e"
uv run pytest -q -m concurrency
# Running demo stack with synthetic seed, credentials via env; no real data:
E2E_BASE_URL=https://localhost:8443 E2E_USER='<synthetic-user>' E2E_PASSWORD='<secret-from-env>' uv run pytest -q -m e2e
```

- [ ] Step 4 — Capture screenshots `home-1672x941.png`, `home-1280x900.png`, `home-390x844.png` and 1 year-filter-after screen; manual compare `reference/home-approved.png`. No claim of pixel-identical text/sizes across AI mockups. Record discrepancy table with `MATCH / DEVIATION ACCEPTED / BLOCKER`.
- [ ] Step 5 — Run `uv run python manage.py check --deploy` with demo env, re-test login/logout & admin deny, no HTMX CSRF regressions, no real credentials/log leaks.
- [ ] Step 6 — Final commit `test(ui): verify homepage design and preserve end-to-end workflow`; deliver screenshots, command outputs, hashes, known deviations. **Do not merge/deploy to public without owner signoff.**

## Deliverable checklist

- [ ] Design system has named tokens and shared components; no duplicated sidebar/header/footer.
- [ ] Homepage `Xin chào, ...`, 4 real KPI, functional tabs, table and nearby search/filter.
- [ ] Header account and in-web unread count; logout POST; no ghost admin links.
- [ ] Calendar/reminder right rail built on scoped data (not mock numbers).
- [ ] Footer department/unit context read-only + functional year selector persisted in session.
- [ ] Business domain unchanged: no description field added, no new migration unless formally approved.
- [ ] Main, list, report scoped to selected year consistently; when viewing historical record via direct URL, view remains permitted irrespective of selected year (year is view filter, not authorization).
- [ ] All tests executed and reported with real outputs; screenshots produced from live running app; E2E old flow updated.
- [ ] Test viewports 1672×941 / 1280×900 / 390×844; accessibility and overflow reviewed.
- [ ] User can revert UI branch without rolling back business data.

## Implementation risks / owner checkpoints

1. **Ảnh có trích yếu nhưng model không có:** không bổ sung; để UI sử dụng thông tin thật sẵn có, muốn trích yếu phải có quyết định mới, phân loại dữ liệu và migration riêng.
2. **“Năm làm việc” là business year hay created year?** Thiết kế v1 dùng năm tạo bản ghi vì không có field. Đây là ASSUMPTION minh bạch, tách ADR nếu cần nghiệp vụ năm tài khóa/năm hồ sơ.
3. **Đơn vị công tác vs phòng ban:** footer hiển thị `user.department` theo ảnh, gắn metadata `user.unit`; không tạo chức năng đổi đơn vị.
4. **Admin role:** không ép hình ảnh mô phỏng lãnh đạo = quản trị kỹ thuật. Quyền source of truth tại backend.
5. **Bảo mật khi demo kết nối mạng:** không mở public deploy, không dùng thông tin thật, logo/biểu trưng chỉ khi có quyền.

## Source references inspected (as of 2026-11-15)

- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/templates/base.html`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/templates/records/dashboard.html`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/apps/records/views.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/apps/records/queries.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/apps/records/forms.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/apps/records/models.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/apps/accounts/models.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/apps/notifications/context_processors.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/tests/e2e/test_browser_flow.py`
- `https://github.com/hoangtien07/cand-nhac-viec/blob/main/docs/ACCEPTANCE_REPORT.md`

## Handoff

Plan/spec đã được tạo bên ngoài repo để owner review. **Không có file nào được push vào `main`; chưa code hay chạy test trong repo.** Khi owner chấp nhận, copy `DESIGN_SPEC.md` tới `docs/superpowers/specs/2026-11-15-home-ui-design.md`, `IMPLEMENTATION_PLAN.md` tới `docs/superpowers/plans/2026-11-15-home-ui-redesign.md` và kèm ảnh tham chiếu an toàn vào docs (nếu được phép), triển khai trong feature branch.
