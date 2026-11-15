# AGENTS.md — Quy tắc bắt buộc cho coding agent

## Nguồn sự thật và thứ tự ưu tiên

1. Yêu cầu người dùng đã chốt trong `CONTEXT.md`.
2. Invariants/ADR trong `ARCHITECTURE.md`.
3. Mặc định demo có gắn nhãn `ASSUMPTION` trong `CONTEXT.md`.
4. `PLAN.md`, `ACCEPTANCE.md`.
5. Bản thiết kế ảnh / ví dụ UI: chỉ mang tính minh họa, **không** được đảo ngược nghiệp vụ đã chốt.

## Must do

- Chỉ triển khai stack **Django 5.2 LTS + Django Templates + HTMX + Tailwind CSS + PostgreSQL**. Không thêm frontend SPA riêng, hệ thống task/project quản lý đầy đủ hay tác vụ không cần thiết.
- Trước khi code: đọc đủ 6 file, khám trạng thái repo, xem `git status`, branch, code đang tồn tại; không ghi đè công việc user.
- Đặt **CUSTOM_USER_MODEL trước migration đầu tiên**. Tách apps logic `accounts`, `organization`, `records`, `notifications`, `audit`, `reports` (có thể gộp tối đa nếu có ADR); business rules ở service/policy, không đặt trong template/HTMX.
- Toàn bộ truy vấn danh sách/detail/report/notification + POST phải lọc theo **organization boundary và record authorization** trên server. Kiểm tra quyền **tại thời điểm submit**, không dựa vào việc từng mở được trang.
- Không dùng `is_staff`/`is_superuser` của Django như giấy phép đọc hồ sơ. Không đăng ký các bản ghi nghiệp vụ vào Django Admin theo cách khiến admin kỹ thuật thấy toàn bộ.
- Nộp kết quả thông qua **một transaction PostgreSQL** có khóa `WorkRecord` (`select_for_update`); tạo ResultReference + audit + (nếu first submit) chuyển status DONE và resolve nhắc hạn. Kiểm tra retry, duplicate và concurrent submit thật bằng PostgreSQL.
- `submitted_at`, `completed_at`, `created_at` đối với sự kiện hồ sơ/kết quả/audit là **thời gian DB**. Lưu UTC, hiển thị giờ Việt Nam; browser không cung cấp timestamp cho các trường này.
- Nhắc hạn chỉ trong web; không gửi email/SMS/push, không tạo reminder sau khi hoàn thành. Quá hạn thông báo assignees và quản lý có quyền.
- Không lưu file, nội dung nghiệp vụ, thông tin công dân, thông tin điều tra, bí mật nhà nước, dữ liệu thực từ hệ thống ngành vào app demo, fixtures, log hoặc ảnh màn hình.
- Dùng POST + CSRF cho mọi mutation, session auth, HTTPS khi truy cập qua mạng, secure cookies, chống brute force, minimal logging, app assets local (không bắt buộc CDN).
- Tạo seed **giả lập**, bộ test tự động và CLI chạy demo; README vận hành rõ lệnh khởi động/backup/restore/migration.

## Must not do

- Không tạo subtask, workflow phê duyệt kết quả, các trạng thái dự án phức tạp, attachment/OCR, agent AI, tích hợp ERP/eOffice/dân cư, offline/mobile app.
- Không chuyển các `ASSUMPTION` thành tuyên bố chính sách ngành; không suy luận quyền từ tên/biểu trưng/hình ảnh.
- Không dùng SQLite làm bằng chứng cho kiểm thử khóa hàng đồng thời (chạy tests transaction trên **PostgreSQL**).
- Không dùng hard delete đối với result/audit; không ẩn hay xóa dấu vết sửa người giao, assignee, watchers, hạn và số hiệu.
- Không phát hành public URL hoặc secret, không tạo admin mặc định password cố định, không tự deploy thật.
- Không báo DONE khi chưa chạy tests. Viết `NOT RUN` cho các kiểm thử chưa thể thực hiện.

## Quy ước triển khai

- Mọi nhánh tính năng: model/migration → policy/service → form/URL/view → template → audit/notifications → tests.
- Mọi tác vụ ghi có side effect phải có idempotency hoặc xử lý retry; không phát nhiều notification giống nhau cho cùng kỳ hạn/recipient/record.
- Ghi các thay đổi thiết kế vào `docs/ADR-*.md` **chỉ khi thực sự phát sinh thay đổi**. Không mở rộng số lượng tài liệu vì mục tiêu hình thức.
- Mỗi phase trả lời: thay đổi gì, chạy lệnh nào, pass/fail, còn rủi ro gì, commit nào. Giữ hành vi của user và mô hình quyền làm chuẩn.
- Khi chỗ chưa rõ có ảnh hưởng bảo mật, ưu tiên **deny by default** và ghi rõ cho owner quyết định trước pilot thực.

## Definition of Done

Tính năng chỉ DONE khi có đường dùng thực từ giao diện, backend auth, kiểm tra policy, migration, server-side validation, audit (khi liên quan), negative cases và tests pass, không chỉ ảnh chụp màn hình.
