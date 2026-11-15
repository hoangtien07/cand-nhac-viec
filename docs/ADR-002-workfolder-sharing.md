# ADR-002: WorkFolder (nhóm hồ sơ) thay cho "Team nhân sự" + lớp quyền chia sẻ tường minh

**Status: PROPOSED — chờ owner duyệt 4 mặc định đề xuất (§3) trước khi dùng dữ liệu thật.**
Branch: `feat/workfolder-sharing`. Nguồn: `DECISIONS_AND_PERMISSIONS.md` (addendum v2, 2026-11-15).

## 1. Quyết định

- "Nhóm" trong yêu cầu nghiệp vụ được hiểu là **WorkFolder** — một tập hợp hồ sơ (folder-like collection),
  **không phải** Team/đơn vị nhân sự mới. `Department` vẫn là đơn vị nhân sự chính thức duy nhất.
- `WorkFolder` một cấp (không folder cha/con ở v1), thuộc một `Unit` và một `owner_department`.
  Một `WorkRecord` nằm trong **tối đa một** folder hoặc không thuộc folder nào (`folder` NULL).
- Quyền xem chéo phòng chỉ đến từ **grant tường minh** trong cùng unit:
  `FolderGrant(role ∈ MANAGER|CONTRIBUTOR|VIEWER)` và `RecordShare(access=VIEWER)`.
  Grant không bao giờ vượt biên `Unit`; `SYS_ADMIN` không được cấp và không tự ý cấp.
- Lớp grant là **disjunct bổ sung** trong `visible_records_queryset`; không thay thế quan hệ
  assignee/watcher/creator hiện có, không nới `assignable_users()`, không đổi
  `can_submit_result` (chỉ assignee active), không đổi `report_records_queryset` ở v1.
- Revocation là soft (`revoked_at`), append-only audit; gỡ grant folder không gỡ
  RecordShare/assignee độc lập.

## 2. Lý do (đối chiếu alternatives)

| Phương án | Vì sao loại |
|---|---|
| Team = nhóm nhân sự mới | Trùng khái niệm Department; nghiệp vụ chốt "nhóm = nơi gom hồ sơ", không phải tổ chức |
| Recursive folder tree + inherited ACL | Phức tạp kiểm chứng (cycle, revoke cascade); v1 không cần |
| Share qua watcher | Watcher có ngữ nghĩa riêng (nhận nhắc hạn); không gộp vào ACL |
| Đổi `can_submit_result` cho folder contributor | Phá invariant "chỉ assignee active nộp kết quả" (CONTEXT C, ARCHITECTURE §4) |

## 3. ASSUMPTION tags — 4 mặc định đề xuất (DECISIONS §7), chưa là chính sách ngành

| Tag | Mặc định demo (bảo thủ, testable) |
|---|---|
| `ASSUMPTION-F1` | Folder VIEWER/CONTRIBUTOR/MANAGER thấy **toàn bộ** hồ sơ trong folder (kể cả hồ sơ tạo sau). |
| `ASSUMPTION-F2` | Chia sẻ trực tiếp 1 hồ sơ: được phép cho creator/assigner, leader, owner-dept manager, folder MANAGER của folder chứa hồ sơ; chia sẻ VIEWER **không** kèm quyền assign/submit. |
| `ASSUMPTION-F3` | Contributor phòng khác **không** được tạo hồ sơ vào folder nếu chính sách tạo hiện hữu không cho phép (`can_create_record` với owner_department của folder vẫn phải đúng). |
| `ASSUMPTION-F4` | "Dự án" chỉ là tên hiển thị của folder; không có entity Project riêng. |

Nếu owner đổi bất kỳ mặc định nào, chỉnh test tương ứng (`tests/test_folder_*.py`, đánh dấu tag trong tên/docstring) — không chỉnh policy rải rác.

## 4. Hệ quả

- Mutation folder (create/grant/revoke/share/move) chạy trong `transaction.atomic`, khóa row liên quan,
  audit `folder.*`/`record.share_*`/`record.folder_moved`, metadata tối thiểu.
- `record.folder.owner_department` phải bằng `record.owner_department` ở v1 (constraint + service check);
  move record sang folder phòng khác = từ chối (đổi chủ trì là thao tác riêng, cần quyết định sau).
- UI cảnh báo khi cấp folder grant: "thành viên thấy toàn bộ hồ sơ trong nhóm, kể cả hồ sơ tạo sau".
- Mọi queryset list/report/search/notification giữ nguyên unit boundary; grant chỉ thêm điều kiện OR bên trong cùng unit.
