# ACCEPTANCE.md — Bộ kiểm thử nghiệm thu bắt buộc

**Quy tắc:** Bảng dưới là yêu cầu kiểm thử, **không phải tuyên bố đã PASS**. Agent phải ghi command + commit + kết quả thực tế. Test đồng thời và chính sách quyền bắt buộc chạy trên **PostgreSQL**, không chỉ mock/SQLite.

## 1. Ma trận nghiệm thu (MUST)

| ID | Điều kiện kiểm thử | Kết quả kỳ vọng |
|---|---|---|
| A01 | User đăng nhập đúng/sai | Đúng mở dashboard; sai không leak account details; logout hết session |
| A02 | Người dùng ngoài unit truy cập URL record | Không thấy record, không suy ra sự tồn tại; POST cũng bị cấm |
| A03 | Admin kỹ thuật vào danh sách/detail/report business | Mặc định denied; vẫn quản lý user/phòng trong phạm vi kỹ thuật |
| A04 | Officer tạo hồ sơ trong phòng mình | Được, tạo 1 record, assigner/creator/time/audit hợp lệ |
| A05 | Officer tự giao assignee khác phòng | Denied theo mặc định demo; không sửa DB |
| A06 | Leader giao assignees từ 2 phòng trong cùng unit | Được, không mở quyền xem toàn đơn vị cho assignees |
| A07 | Một hồ sơ có 3 assignees, 2 watchers | Quan hệ được lưu; giao diện hiển thị đủ; không tạo subtask |
| A08 | Trưởng phòng xem hồ sơ phòng chủ trì | Được; manager khác không có participant/share thì không xem |
| A09 | Trưởng phòng xem hồ sơ do phòng khác chủ trì nhưng có subordinate assigned | Được theo phạm vi phối hợp đã quy định; không xem hồ sơ khác cùng phòng ngoài scope |
| A10 | Officer chỉ là watcher truy cập hồ sơ | Đọc được, **không** nộp kết quả/chỉnh hạn/giao việc |
| A11 | Assignee nộp mã số hợp lệ đầu tiên | Result lưu; status DONE; completed_at/completed_by ghi một lần; không chờ duyệt |
| A12 | Nộp nhiều số hiệu sau DONE bởi assignee active | Thêm kết quả; `completed_at`/`completed_by` giữ nguyên; audit đầy đủ |
| A13 | Hai assignees submit hai mã khác nhau đồng thời | Hai result, một transition OPEN→DONE, một completed audit event |
| A14 | Lặp POST cùng mã/khởi chạy retry | Không tạo result hoặc completion event trùng |
| A15 | Mã trắng, vượt maxlength, hoặc không hợp lệ | 400/validation error an toàn, record không bị đóng |
| A16 | Assignee bị thu hồi quyền rồi submit qua URL đã mở từ trước | Denied server-side, không lưu result |
| A17 | `submitted_at`, `completed_at` | Từ DB clock, không chấp nhận timestamp browser; hiển thị giờ VN |
| A18 | Gần hạn, chưa DONE | Notification được tạo theo lịch, chỉ người được phép nhận |
| A19 | Quá hạn | Nhắc assignees + quản lý phòng chủ trì; leader thấy chỉ số dashboard |
| A20 | Command reminder chạy lặp cùng kỳ | Không tạo duplicate notification |
| A21 | Kết quả được nộp trước khi scheduler gửi reminder | Không tạo reminder mới sau DONE |
| A22 | Scheduler và submit chạy cạnh tranh | Không có active overdue reminder sau DONE; notification history không bị xóa |
| A23 | List/search/report filter qua phòng/unit | Chỉ đếm/hiển thị record được phép, không leak qua tổng hợp |
| A24 | Audit create/assign/deadline/result/complete | Đủ actor, DB timestamp, thay đổi hợp lệ; không hard delete |
| A25 | Không có file upload, nội dung hồ sơ, email/SMS, subtask | Giao diện, endpoint, DB đều không phát sinh chức năng này |
| A26 | Dữ liệu demo, quyền truy cập | Không có dữ liệu thật/credential mặc định; HTTPS/DEBUG off khi deploy ngoài máy local |
| A27 | Restore backup | Khôi phục bản sao DB test và đọc đủ các bản ghi, không chỉ tạo file dump |
| A28 | Trình duyệt không chuyên CNTT | Thực hiện login → hồ sơ của tôi → nộp số hiệu → thấy DONE bằng UI tiếng Việt |

## 2. Dữ liệu kiểm thử giả lập chuẩn

Tạo bởi management command `seed_demo` (không chứa trong spec pack):

- `Unit A`: Phòng Tổng hợp, Phòng Địa bàn; leader A, 2 managers, 4 officers, admin kỹ thuật riêng.
- `Unit B`: Phòng Nội bộ, Phòng Hành chính; leader B, 2 managers, 3 officers.
- `Record R1`: OPEN, 2 assignees cùng phòng, 1 watcher, gần hạn.
- `Record R2`: OPEN, 2 assignees khác phòng, quá hạn, manager phòng chủ trì nhận nhắc.
- `Record R3`: DONE, 2 số hiệu kết quả, không có active deadline reminder.
- `Record R4`: OPEN trong Unit B, hoàn toàn không hiển thị với Unit A.
- `Record R5`: OPEN, watcher từ cùng unit nhưng khác phòng, không có quyền submit.
- Không sử dụng tên, số hiệu, email hoặc bộ hồ sơ thực của cơ quan/đơn vị.

## 3. Race tests phải có bằng chứng

1. Khởi tạo R1 OPEN với 2 assignees hợp lệ.
2. Tạo hai connection PostgreSQL độc lập, đồng bộ 2 request POST cùng thời điểm, cùng hoặc khác mã.
3. Assert khác mã → 2 `ResultReference`, 1 `record.completed`; cùng mã → 1 `ResultReference`, 1 `record.completed`.
4. Assert time/completed_by không đổi khi thêm result thứ ba sau DONE.
5. Khởi tạo R2 OPEN overdue; chạy scheduler và submit chéo nhau; assert cuối cùng không có active deadline reminder sau DONE.
6. Ghi log command, DB backend, version Postgres và test result. Nếu không dựng được concurrency fixture, đánh `NOT RUN` và BLOCKED P3/P6.

## 4. Council checkpoint cuối — câu hỏi phản biện

- **Nghiệp vụ:** Người được giao có hoàn thành chỉ bằng 1 số hiệu trong một màn hình không? Có phát sinh task con/phê duyệt thừa không?
- **Quyền:** Admin kỹ thuật có xem hồ sơ trái quyền? Manager đọc hồ sơ không liên quan từ phòng khác? Cross-unit leak qua reports/notifications?
- **Concurrency:** Hai người nộp đồng thời có một lần đóng duy nhất? Reminder có thể xuất hiện sau close?
- **UX:** Cán bộ ít kỹ năng IT có tìm được hồ sơ/nút nộp không? Có nhầm “số hiệu kết quả” với file upload không?
- **SRE/Security:** Có backup/restore test, auth/session, HTTPS, logs tối thiểu, quy trình deploy lại từ sạch?

## 5. Mẫu báo cáo nghiệm thu agent phải điền

```text
Commit: <hash>
Environment: Python=<...>, Django=<...>, Postgres=<...>, Docker=<...>
Unit tests: <command> => PASS/FAIL/NOT RUN
Integration tests (PostgreSQL): <command> => PASS/FAIL/NOT RUN
Concurrency tests: <command> => PASS/FAIL/NOT RUN
Security checks: <command> => PASS/FAIL/NOT RUN
Browser/manual demo: <scenario> => PASS/FAIL/NOT RUN
A01..A28: <case-by-case status>
Known limitations: <...>
Open assumptions requiring owner's decision: H01..H08 from CONTEXT.md
Decision: READY_FOR_CONTROLLED_DEMO / BLOCKED
```

`READY_FOR_CONTROLLED_DEMO` chỉ cho phép dùng dữ liệu giả lập trong môi trường được phép; **không đồng nghĩa** hệ thống có đủ quyền/đủ điều kiện cho nghiệp vụ thực tế.
