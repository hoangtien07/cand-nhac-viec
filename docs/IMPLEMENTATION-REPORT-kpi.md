# Báo cáo triển khai — plan `PLAN_CAND_NHAC_VIEC_KPI_CONFIG_MAIN` (base 8d59b95)

Branch: `devin/kpi-config-main`. Ngày: 2026-11-18. Tests: `uv run pytest -q -m "not e2e"` → **257 passed, 6 deselected** trên PostgreSQL 16 (không dùng SQLite).

## Trạng thái theo work package

| WP | Nội dung | Files chính | Migrations | Commit | Tests |
|----|----------|-------------|------------|--------|-------|
| WP0 | ADR-004 (KPI cấu hình), ADR-005 (văn bản định kỳ), CONTEXT §H | `docs/ADR-004-*.md`, `ADR-005-*.md`, `CONTEXT.md` | — | `2b9f85f` | — |
| WP1 | Bỏ "Đang xử lý"/watcher khỏi UI, đổi nhãn, seed 5 tổ + 2 lãnh đạo + cán bộ | `apps/records/views.py`, `templates/*`, `seed_demo.py` | — | `8e6525a` | `tests/test_scope.py` |
| WP2 | `task_kind` DOCUMENT/OTHER + `PeriodicPlan` (1–12 kỳ/năm) + period children | `apps/records/models.py`, `services.py`, `periodic_views` | records 0009 | `416378e` | `tests/test_periodic_plans.py` (10) |
| WP3 | `apps/kpi` schema + `KpiCapabilityGrant` + `KPI_ENABLED` flag | `apps/kpi/models.py`, `policies.py`, `capabilities.py`, `grant_views.py` | kpi 0001, 0002 (append-only triggers) | `81ac879` | `tests/test_kpi_permissions.py` (9) |
| WP4 | Config CRUD DRAFT + validation (sum=100, band không chồng/hở) + publish | `apps/kpi/services.py`, `views.py`, `forms.py`, `templates/kpi/config_*` | — | `9d676a2` | `tests/test_kpi_config.py` (13) |
| WP5 | Reminder events + evaluation + score engine + finalize + correction | `reminder_services.py`, `evaluation_services.py`, `scoring.py` | — | `9fce547` | `tests/test_kpi_scoring.py` (14) |
| WP6 | UI theo role + cột "Đánh giá"/"Điểm KPI" | `apps/kpi/queries.py`, `views.py`, `templates/kpi/*`, `records` views/templates | — | `a7986ef` | 5 test UI trong test_kpi_scoring |
| WP7 | Báo cáo: tách plan/period; chỉ aggregate FINALIZED effective | `apps/reports/views.py`, `templates/reports/report.html` | — | `52e9889` | 1 test report |
| WP8 | Tests + docs + seed grants leader.config/leader.approve + report này | `seed_demo.py`, `tests/test_scope.py`, `README_RUN.md`, file này | — | (commit WP8) | 257 tổng |

## Quyết định đáng chú ý

- **Append-only**: `KpiScoreSnapshot`, `KpiScoreCorrection`, `KpiReminderEvent`, `KpiReminderRevocation` chặn UPDATE/DELETE bằng trigger plpgsql `pocketops_reject_mutation()` (kpi 0002) + `AppendOnlyQuerySet` ở tầng app.
- **Finalize**: `select_for_update` evaluation + policy version; gate `status==DRAFT` + version vẫn `ACTIVE` + đủ marks + `record.status==DONE`; double-POST/concurrent trả về cùng snapshot (idempotent qua unique `(evaluation, revision)`).
- **Correction**: snapshot mới `revision+1` + `KpiScoreCorrection(reason, requested_by=approved_by=actor)` — giả định MVP: người có `KPI_SCORE_CORRECT` tự duyệt; luồng duyệt 2 người là quyết định nghiệp vụ chưa chốt (D09).
- **Effective snapshot**: resolve qua corrections (không có cờ mutable — append-only cấm UPDATE).
- **idempotency_key** unique per unit; form render uuid per assignee (key phải riêng theo subject vì ràng buộc unit-wide).
- **Báo cáo**: `periodic_stats` đếm `periodic_plan` distinct vs `period_index` riêng; `kpi_stats` chỉ FINALIZED + loại snapshot bị thay thế; officer → chỉ số liệu của mình; không leaderboard.
- **OPEN DECISIONS D01–D17**: không tự quyết — cấu hình mẫu giữ DRAFT, gate `BLOCKED_BY_BUSINESS_DECISION` giữ nguyên như plan yêu cầu.

## Rủi ro còn lại

- `KpiEvaluation` và reminder events cập nhật mỗi request đọc DB-time — chấp nhận được ở quy mô demo.
- Correction chưa có luồng phê duyệt 2 người (xem D09).
- Snapshot build VM dùng PostgreSQL có sẵn; production migration chưa chạy (không được phép deploy/migrate thật).
- Push chưa thực hiện: tích hợp GitHub của Devin không có quyền ghi vào `hoangtien07/cand-nhac-viec` — cần PAT của chủ repo (scope `workflow` nếu sửa workflow, `repo` đủ cho code) hoặc user tự push.
