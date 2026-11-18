# ADR-005 — Loại nhiệm vụ và văn bản định kỳ (PeriodicPlan)

**Status: PROPOSED (implementation per plan v1.0, 18/11/2026). Quyết định nghiệp vụ chưa chốt
ở lại CONTEXT.md §D12.**

## Bối cảnh

Excel yêu cầu (STT 7, 10): "nhiệm vụ khác" tương đương văn bản (không bắt buộc số hiệu gốc)
và văn bản định kỳ tối đa 12 hạn/năm. Baseline `WorkRecord` có `reference_no` bắt buộc và
một `due_at` duy nhất.

## Quyết định

1. **`WorkRecord` giữ vai trò đơn vị thực hiện**: một hạn, một trạng thái, một điểm chấm —
   không viết lại `submit_result_reference` đang có kiểm soát concurrency.
2. **`task_kind`**: `DOCUMENT` (mặc định cho toàn bộ dữ liệu cũ, giữ `reference_no` bắt
   buộc và flow nộp số hiệu) và `OTHER` (nhiệm vụ khác: `title` bắt buộc, `reference_no`
   tùy chọn). `task_code` mã nội bộ tự sinh, unique theo đơn vị, phân biệt nhiệm vụ mà
   không phụ thuộc số hiệu văn bản.
3. **`PeriodicPlan`**: 1 kế hoạch → **1..12 `WorkRecord` con**, mỗi con một `period_index`,
   một `due_at`, một `OPEN/DONE`, nộp kết quả và chấm KPI độc lập. Nộp kết quả kỳ 1 chỉ
   `DONE` kỳ 1. Tạo kế hoạch trong một transaction có khóa; validate ngày thuộc năm, sorted,
   không trùng, unique `(plan, period_index)`.
4. **Thống kê tách hai khái niệm**: số văn bản định kỳ (`PeriodicPlan`) vs số kỳ thực hiện
   (`WorkRecord` con). Không cộng một văn bản 12 hạn thành 12 văn bản.
5. **Hoàn thành `OTHER`** (D12 chưa chốt quy tắc chứng cứ): MVP áp dụng quy tắc bảo thủ —
   assignee active xác nhận hoàn thành qua POST có xác nhận, transaction + khóa record +
   audit giống `submit_result_reference`. Quy tắc này được đánh dấu trong báo cáo là chờ
   phê duyệt; có thể siết lại khi nghiệp vụ chốt.

## Hệ quả

- `reference_no` chuyển sang nullable; `DOCUMENT` vẫn validate bắt buộc ở service/form.
- Migration legacy: mọi `WorkRecord` cũ thành `DOCUMENT`, `title` = `reference_no`,
  `task_code` sinh ngẫu nhiên; không backfill KPI.
- KPI version được pin tại thời điểm tạo kỳ (D11 — đề xuất, chờ xác nhận trước pilot).
