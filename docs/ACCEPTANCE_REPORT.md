# Acceptance report — CAND PocketOps (controlled demo)

- Code commit tested: `1dbc602` (+ dev-settings CSRF env tweak in the report commit; no business-logic change).
- Environment: Ubuntu VM, Python 3.12, Django 5.2.19, PostgreSQL 16.16 (Docker `postgres:16-alpine`), Chromium 159 (Playwright 1.65.2).
- Data: synthetic only (`seed_demo`: 2 units, 4 departments, 15 accounts, 6 records). Random per-account passwords, file 0600, never committed.

## Commands run (2026-11-15, VN time)

| Command | Result |
|---|---|
| `uv run ruff check . && uv run ruff format --check .` | PASS |
| `DJANGO_SETTINGS_MODULE=config.settings.test manage.py makemigrations --check --dry-run` | PASS (No changes detected) |
| `uv run pytest -q -m "not e2e"` (PostgreSQL) | PASS — 71 passed |
| `uv run pytest -q -m concurrency` | PASS — 9 passed (2 independent PG backends verified via `pg_backend_pid`; lock-contended variant asserts workers are waiting in `pg_stat_activity`) |
| `E2E_BASE_URL=https://localhost:8443 … pytest -m e2e` (compose stack, desktop 1280px + mobile 390px) | PASS — 2 passed |
| `uv run pip-audit` | PASS — No known vulnerabilities found |
| `manage.py check --deploy` (demo settings, HSTS 1y) | PASS with 2 warnings: W005 `SECURE_HSTS_INCLUDE_SUBDOMAINS`, W021 `SECURE_HSTS_PRELOAD` — intentionally off (domain unknown, owner decision) |
| `docker compose up -d --build` → db/web/scheduler/proxy | PASS — web healthy, `/login/` 200 over HTTPS, HSTS/secure `__Host-` cookies/XFO DENY/nosniff present; scheduler ran `send_due_reminders` |
| `scripts/restore_drill.sh` | PASS — live vs restored: units=2 users=15 records=6 done=1 results=2 audit=12 notifications=8; append-only trigger still rejects DELETE on restored DB |
| GitHub Actions CI (`.github/workflows/ci.yml`) | NOT RUN — remote repo not created yet |

## A01–A28

| ID | Status | Evidence |
|---|---|---|
| A01 | PASS | `tests/test_auth.py` (login ok/logout, same generic error for wrong pw/unknown user, lockout after 5, GET logout 405) |
| A02 | PASS | `test_authz.py::test_cross_unit_get_and_post_are_404_and_no_write`, `…leader_sees_nothing_and_search_does_not_leak` |
| A03 | PASS | `test_technical_admin_denied_business_but_manages_users`, `test_superuser_flags_grant_nothing` (`/admin/` not mounted) |
| A04 | PASS | `test_records.py::test_officer_creates_in_own_dept_via_ui` |
| A05 | PASS | `test_officer_cannot_assign_other_dept`, `test_officer_cannot_create_for_other_dept` |
| A06 | PASS | `test_leader_assigns_two_departments_without_widening_scope` |
| A07 | PASS | `test_three_assignees_two_watchers_displayed` |
| A08 | PASS | `test_authz.py::test_manager_scope` |
| A09 | PASS | `test_authz.py::test_manager_scope` |
| A10 | PASS | `test_watcher_reads_but_cannot_mutate` |
| A11 | PASS | `test_submit.py::test_two_step_ui_first_submit_closes_record` (+ leader non-assignee denied) |
| A12 | PASS | `test_additional_results_after_done_keep_completion` |
| A13 | PASS | `test_concurrency.py::test_concurrent_different_codes_one_completion[lock-contended,barrier]`, `test_concurrent_http_posts` |
| A14 | PASS | `test_concurrent_same_code_one_result[*]`, `test_duplicate_normalized_code_is_idempotent[4 variants]`, `test_retry_post_same_code_via_ui` |
| A15 | PASS | `test_invalid_codes_rejected_and_record_stays_open[6 cases]` |
| A16 | PASS | `test_revoked_assignee_denied_on_stale_page`, `test_deactivated_user_cannot_submit` |
| A17 | PASS | `test_timestamps_from_db_and_browser_timestamp_ignored` (DB `statement_timestamp`, VN display) |
| A18 | PASS | `test_reminders.py::test_due_soon_d1_only_active_assignees`, `test_due_today`, `test_deadline_boundary_2359_vn` |
| A19 | PASS | `test_overdue_includes_owner_manager_daily`, `test_dashboard_derived_overdue_state` |
| A20 | PASS | `test_repeated_runs_same_bucket_no_duplicates`, `test_management_command_runs` |
| A21 | PASS | `test_no_reminder_after_done_and_existing_resolved` |
| A22 | PASS | `test_scheduler_vs_submit_no_active_reminder_after_done[*]`, `test_scheduler_first_then_submit_keeps_history` |
| A23 | PASS | `test_reports_counts_only_scope`, cross-unit search test |
| A24 | PASS | `test_assignment_watchers_deadline_changes_are_audited_and_soft`, `test_result_audit_and_completion_are_immutable_in_db` (PG triggers) |
| A25 | PASS | `test_scope.py` (no FileField/file input/multipart/email/CDN, only OPEN/DONE) |
| A26 | PASS (local) | `test_seed_is_synthetic_and_has_no_fixed_password`, `test_demo_settings_secure`, compose HTTPS headers. Network deployment with real certificate: NOT RUN (no deploy by policy) |
| A27 | PASS | `scripts/restore_drill.sh` output above |
| A28 | PASS (automated) | `tests/e2e/test_browser_flow.py` login → Việc của tôi → open record → nhập số hiệu → xác nhận → "Đã hoàn thành" → logout, desktop + mobile. Test with a real non-IT user: NOT RUN |

## Known limits / owner decisions before any real pilot

- H01–H08 are demo ASSUMPTIONs from CONTEXT.md, not policy.
- HSTS subdomains/preload off; HTTPS cert in compose is Caddy internal CA (localhost only).
- Overdue/due-soon boundary is `now > due_at` where `due_at` = 23:59:59.000 VN.
- Officer who created/assigned a record may manage its assignees (same department only), watchers and deadline (per ARCHITECTURE authorization matrix as implemented in `apps/records/policies.py`).

## Verdict

READY_FOR_CONTROLLED_DEMO (local/controlled). CI on GitHub and real-user usability test remain NOT RUN.
