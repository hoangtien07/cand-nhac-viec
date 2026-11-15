# Home UI redesign — evidence (branch `feat/home-ui-design-system`)

Baseline: `main` @ `3b183d3` (same as the spec baseline, so no diff review was needed). Spec and plan: `docs/superpowers/specs/2026-11-15-home-ui-design.md` and `docs/superpowers/plans/2026-11-15-home-ui-redesign.md`. The reference image is not committed because it contains a CAND emblem whose use is not yet authorised.

## Commits

| Task | Commit |
|---|---|
| 1 Shell (header/sidebar/footer, SVG sprite, tokens) | `6452a39` |
| 2 Work-year selector (session, POST + CSRF) | `93d5bc1` |
| 3 Dashboard KPI/tabs/search/table/pagination | `384c4eb`, then fix `a381bda` |
| 4 Calendar + reminder rail | `f6f490d` |
| 5 Quick actions, shared badge/pagination, list + report by year | `e59dcd9` |
| 6 Responsive/a11y polish + browser assertions | `f5f7101` |
| 7 E2E flow updated to new selectors + this file | see the branch HEAD |

Commit `384c4eb` was committed with one failing test (`test_home_nav_item_is_active_on_dashboard`): the tabs used `aria-current="page"`. Commit `a381bda` fixed it by switching to `aria-current="true"`.

## Commands (run 2026-11-15, PostgreSQL 16 in Docker)

| Command | Result |
|---|---|
| `npm ci && npm run build:css` | PASS (0 vulnerabilities) |
| `uv run ruff check . && uv run ruff format --check .` | PASS |
| `uv run pytest -q -m "not e2e"` | PASS — 113 passed (71 baseline + 42 new across `test_navigation_ui`, `test_work_year`, `test_dashboard_ui`, `test_ui_rollout`) |
| `uv run pytest -q -m concurrency` | PASS — 9 passed |
| `E2E_BASE_URL=https://localhost:8443 … pytest -m e2e tests/e2e` (compose stack, fresh synthetic seed) | PASS — 6 passed: `test_home_ui` (1672×941, 1280×900, 390×844, tabs/search/back/year) + `test_browser_flow` (desktop and mobile submit → DONE → logout) |
| `docker compose exec web python manage.py check --deploy` | PASS with the 2 known warnings W005/W021 (HSTS subdomains/preload intentionally off) |
| axe or any other automated contrast audit | NOT RUN (no a11y tooling installed). The E2E smoke covers: every visible control has an accessible name, skip link first in tab order, focus order skip → header, Esc closes the drawer and returns focus, no horizontal page overflow. |

Screenshot data: a synthetic seed plus 5 extra synthetic records for `canbo.th1` created through `services.create_record`/`submit_result_reference`, added only to the local compose DB to show every status.

## Visual comparison against `home-approved.png`

| Region | Verdict | Note |
|---|---|---|
| Header (navy, brand + Demo, tagline, bell badge, help, avatar + name/department) | MATCH | The logo is a placeholder shield icon, not the CAND emblem (no authorisation). |
| Sidebar (red active "Trang chủ", menu items, badge) | DEVIATION ACCEPTED | "Quản trị" appears only for `SYS_ADMIN`, and that role has no business menu, so no single account sees the image's full menu. "Vai trò & quyền" and "Cấu hình hệ thống" are hidden because no such route exists. |
| Greeting + 4 KPI | MATCH | Real counts, scoped per user and year. 2×2 layout when the main column is ≤900px. |
| "Công việc của tôi": 5 tabs, search next to the table, table | DEVIATION ACCEPTED | "Trích yếu" → "Thông tin hồ sơ" (assigner). No checkbox or star (no matching feature). Below 900px of main-column width the "Thông tin hồ sơ" column is hidden; at 1280px the "Người xử lý" column still scrolls horizontally inside the table (the page itself does not overflow). |
| Right rail: calendar + reminders | DEVIATION ACCEPTED | Title is "Nhắc việc cần xử lý (n)" instead of "hôm nay", because the list holds every actionable reminder, not just today's. Clicking a marked day filters the table with `?due=`. |
| Quick actions | DEVIATION ACCEPTED | Only permitted actions are shown. "Cấu hình hệ thống" is replaced by "Thông báo". |
| Footer: Đơn vị công tác + Năm làm việc | DEVIATION ACCEPTED | Unit/department is read-only, with no dropdown. The year control has an explicit "Áp dụng" button instead of auto-submit, so keyboard arrows do not reload the page. After applying, the user stays on the same page, not the dashboard. |
| Mobile 390px | MATCH (layout per spec §7) | Drawer menu, KPI 2×2, table rows become cards, footer is not fixed. |

No BLOCKER.

## Owner decisions still open

1. "Năm làm việc" = year of `created_at` (VN time). This is the spec ASSUMPTION; whether it should mean another year (e.g. a fiscal year) is undecided.
2. Whether the CAND emblem may be used.
3. Whether to add a "trích yếu" field. This needs a data-classification decision and a migration; it was not done in this round.
