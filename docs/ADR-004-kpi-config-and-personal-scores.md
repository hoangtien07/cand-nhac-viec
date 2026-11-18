# ADR-004 — Phân hệ KPI có cấu hình và điểm cá nhân

**Status: PROPOSED (implementation per plan v1.0, 18/11/2026). Các quyết định nghiệp vụ chưa chốt
ở lại `OPEN DECISIONS` (CONTEXT.md §D17/D01–D17) và các release barrier A/B/C.**

## Bối cảnh

Excel yêu cầu (STT 3, 4, 11): công tác chấm điểm nhiệm vụ theo tiêu chí, cột đánh giá và cột
điểm KPI, lãnh đạo theo dõi điểm từng cán bộ, cán bộ chỉ xem điểm của mình, chậm hạn và
nhắc nhở bị trừ điểm. Excel **không** quy định: tiêu chí cụ thể, trọng số, điểm gốc, cách
kết hợp hai khoản trừ, định danh cán bộ trên tài khoản dùng chung, quy chế chốt điểm.

## Quyết định

1. **App riêng `apps/kpi`.** Không đặt công thức trừ điểm trong template, JS hay
   `apps/reports`. Mọi phép tính bằng `Decimal`, không float.
2. **Policy có version bất biến.** `KpiPolicyFamily (unit, task_kind)` → nhiều
   `KpiPolicyVersion` (`DRAFT → ACTIVE → SUPERSEDED`). Nội dung ACTIVE không được sửa;
   thay đổi = version mới. Chỉ một version ACTIVE cho mỗi `(unit, task_kind)`; publish
   trong transaction khóa family row.
3. **Điểm theo `(WorkRecord, subject_user)`**, không theo record chung và không theo phòng:
   một nhiệm vụ nhiều assignee thì mỗi cán bộ một `KpiEvaluation` riêng. Với văn bản định
   kỳ, mỗi kỳ là một `WorkRecord` nên không double-count.
4. **Capability ≠ role.** `KpiCapabilityGrant` theo `user + unit (+ department scope)`;
   không suy quyền từ `is_staff`/`is_superuser`/share/folder grant. `SYS_ADMIN` không bao
   giờ được cấp quyền nghiệp vụ KPI (kiểm tra khi cấp lẫn khi dùng).
5. **Nhắc nhở KPI tách khỏi `Notification` tự động.** `KpiReminderEvent` do người có quyền
   ghi nhận thủ công, có `idempotency_key`, append-only; `KpiReminderRevocation` append-only
   chỉ loại event khỏi count, không xóa. Thông báo hệ thống `DUE_SOON/DUE_TODAY/OVERDUE`
   không tính vào KPI theo mặc định (D06).
6. **Điểm đã chốt bất biến.** Finalize tạo `KpiScoreSnapshot` (DB trigger append-only);
   sau chốt chỉ điều chỉnh qua `KpiScoreCorrection` trỏ tới snapshot thay thế; snapshot cũ
   giữ nguyên. `effective_snapshot` trên evaluation trỏ bản hiệu lực.
7. **Tách trạng thái nhiệm vụ và trạng thái chấm điểm**: `DONE` ≠ `SCORED`; bản DRAFT của
   evaluation chỉ người chấm/người có quyền xem; officer chỉ thấy điểm FINALIZED của mình.
8. **Feature flag `POCKETOPS_KPI_ENABLED`**: tắt phân hệ khi chưa nghiệm thu; route trả
   404, menu ẩn. Flag không thay thế kiểm tra quyền.
9. **Cấu hình mẫu từ Excel chỉ là DRAFT demo** (`Cần phê duyệt`); không activate, không
   chốt điểm chính thức từ ngưỡng suy diễn cho ngày 5/7 (D04) hay công thức gộp (D05).

## Hệ quả

- Publish/finalize đều `transaction.atomic` + `select_for_update` + re-check grant sau khóa.
- `KpiReminderEvent`, `KpiReminderRevocation`, `KpiScoreSnapshot`, `KpiScoreCorrection` có
  trigger PostgreSQL append-only như `AuditEvent`.
- Báo cáo KPI chỉ tổng hợp snapshot hiệu lực đã chốt; không có "tổng KPI chính thức" cho
  đến khi nghiệp vụ duyệt `aggregation_method` (D08).
