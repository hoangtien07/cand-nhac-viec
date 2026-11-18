# CONTEXT.md — PRD + quy tắc nghiệp vụ + UI

**Project:** CAND PocketOps — web demo quản lý hồ sơ công việc theo số hiệu.  
**Người dùng mục tiêu:** cán bộ, người giao việc, trưởng phòng/đội, lãnh đạo đơn vị; nhiều người không chuyên CNTT.  
**Độ tin cậy:** các mục `CONFIRMED` là người đặt yêu cầu đã chốt; các mục `ASSUMPTION` là mặc định bảo thủ cho demo, cần phê duyệt trước triển khai thực tế.

## A. Mục đích và ranh giới

- Quản lý **hồ sơ công việc bằng số hiệu**, không phải số hóa nội dung hồ sơ, không phải hồ sơ điều tra hay hệ thống quản lý văn bản đầy đủ.
- Chạy **web-only**, kết nối mạng trong môi trường demo được phép; có thể triển khai nội bộ/HTTPS có kiểm soát.
- Nếu sau này được phê duyệt, có thể tích hợp vào phần mềm hiện hữu; **không** phát triển tích hợp trong MVP.
- Không có file upload. Người dùng nói “tạo mới file nộp” nhưng đã làm rõ nghĩa là **nhập số hiệu hồ sơ/văn bản kết quả**; UI phải gọi là “Nộp số hiệu kết quả”, không gọi “Tải tệp lên”.
- Dữ liệu demo **giả lập** và tối thiểu; không chứa tài liệu mật, công dân thật, thông tin tác chiến/điều tra, thông tin nhạy cảm khác.

## B. Những quyết định đã chốt — CONFIRMED

| ID | Quy tắc |
|---|---|
| C01 | Một hồ sơ công việc = một đơn vị công việc; **không có nhiệm vụ con** |
| C02 | Hồ sơ có **người giao**, **1..N assignees**, **0..N watchers**, phòng/đội chủ trì, số hiệu gốc, hạn xử lý |
| C03 | Một hồ sơ có thể giao **nhiều người** cùng lúc |
| C04 | Cán bộ có thể **tạo và giao việc** trong phạm vi được phân quyền; không chỉ lãnh đạo |
| C05 | Người được giao hoàn thành bằng cách nhập **một hoặc nhiều số hiệu hồ sơ/văn bản kết quả** |
| C06 | Ngày giờ nộp **lấy phía cơ sở dữ liệu**; lưu lịch sử create/update, giao việc và thay đổi |
| C07 | Bản ghi kết quả đầu tiên hợp lệ khiến hồ sơ **đóng ngay**, dừng nhắc hạn **không cần người duyệt** |
| C08 | Phân quyền theo **vai trò + đơn vị/phòng ban + quan hệ từng hồ sơ** |
| C09 | Lãnh đạo đơn vị được xem hồ sơ toàn đơn vị; trưởng phòng/đội quản lý hồ sơ phạm vi phòng và phối hợp được quyền |
| C10 | Thông báo **trong web**; **quá hạn** cảnh báo cả người thực hiện và cấp quản lý |
| C11 | Giao diện đơn giản, tiếng Việt, tham khảo UX công cụ quản lý việc hiện đại; không sao chép tính năng thừa |

## C. Trạng thái và công việc

- `OPEN` — hồ sơ còn xử lý; “Sắp đến hạn” và “Quá hạn” **được tính từ hạn**, không lưu như trạng thái riêng.
- `DONE` — hồ sơ đã có ít nhất một số hiệu kết quả hợp lệ.
- **Không tạo** `IN_REVIEW`, `PENDING_APPROVAL`, subtask, % progress hoặc trạng thái phụ.
- Tại thời điểm một người được giao (assignee active) nộp mã kết quả hợp lệ đầu tiên: `OPEN → DONE` **trong cùng transaction** với kết quả và audit; `completed_at` lấy DB; ngừng phát reminder mới.
- **Sau khi DONE**, assignee hiện có vẫn có thể thêm các số hiệu kết quả khác; status/completed_at **không thay đổi**, không tạo sự kiện DONE thứ hai.
- Nhắc hạn cũ phải được đánh dấu đã giải quyết hoặc không còn nằm trong danh sách cần hành động, nhưng audit/notification history vẫn được giữ.
- Không yêu cầu cả nhóm đồng thuận: **một assignee nộp = đóng toàn bộ hồ sơ** (invariant của demo).

## D. Vai trò và phạm vi — ASSUMPTION an toàn, có thể cấu hình lại

### Khái niệm

- **Đơn vị/Unit:** ranh giới dữ liệu tách biệt, không hiển thị chéo dù trùng số hiệu.
- **Phòng/đội/Department:** một nhóm trực thuộc đơn vị; mỗi user có **một phòng chính** ở MVP. Hồ sơ có **một phòng chủ trì**; người được giao có thể đến từ phòng khác nếu quyền cho phép.
- **Người giao (`assigner`):** người đứng tên giao; người tạo (`created_by`) có thể khác nếu được ủy quyền, nhưng MVP mặc định `assigner=created_by`.
- **Watcher:** quan hệ theo dõi trên hồ sơ, **không phải quyền nộp kết quả**.
- **Admin kỹ thuật:** quản lý tài khoản/phòng ban/vai trò, không mặc định được đọc hồ sơ nghiệp vụ.

### Ma trận quyền đề xuất (deny-by-default)

| Hành động | Admin kỹ thuật | Lãnh đạo đơn vị | Trưởng phòng | Cán bộ | Watcher thuần túy |
|---|---|---|---|---|---|
| Quản lý tài khoản/phòng/role | Có | Tùy quyền uỷ quyền (mặc định không) | Không | Không | Không |
| Xem hồ sơ | Không mặc định | Tất cả trong đơn vị | Hồ sơ phòng chủ trì hoặc phòng có assignee được quyền | Hồ sơ mình tạo/giao/được giao/theo dõi | Chỉ hồ sơ được gắn watcher |
| Tạo hồ sơ | Không mặc định | Có | Trong phạm vi phòng quản lý | Trong phòng của mình | Không chỉ vì là watcher |
| Giao/đổi người xử lý | Không mặc định | Trong đơn vị | Trong phạm vi quản lý | Chỉ hồ sơ mình tạo/giao, assignees trong phòng của mình | Không |
| Giao liên phòng | Không mặc định | Có | Chỉ nếu được cấp quyền cụ thể (mặc định không) | **Không trong demo** | Không |
| Thay đổi hạn | Không mặc định | Có | Hồ sơ thuộc phạm vi quản lý | Chỉ hồ sơ mình tạo/giao còn OPEN, cùng phòng | Không |
| Nộp số hiệu kết quả | Không | Chỉ nếu đồng thời là assignee active | Chỉ nếu đồng thời là assignee active | **Chỉ assignee active** | Không nếu không là assignee |
| Xem báo cáo | Không mặc định | Toàn đơn vị | Phòng được quản lý | Hồ sơ cá nhân được quyền | Không mặc định |
| Xem audit hồ sơ | Không mặc định | Trong phạm vi đơn vị | Hồ sơ được quản lý | Chỉ hồ sơ mình được quyền xem | Chỉ hồ sơ được theo dõi |

Người vừa là watcher vừa là assignee được quyền nộp nhờ vai trò **assignee**, không phải watcher. Trưởng phòng có thể thấy công việc phòng mình được giao tham gia ở phòng khác, nhưng không thấy toàn bộ hồ sơ phòng khác. Những giao dịch liên phòng phải có actor đủ quyền và audit rõ.

### Điểm chưa xác nhận / cần hỏi trước triển khai thật

- `H01`: Cán bộ có được **giao liên phòng** hay chỉ lãnh đạo? **Mặc định demo:** chỉ lãnh đạo đơn vị được giao liên phòng.
- `H02`: Số hiệu gốc có tái sử dụng theo năm, loại văn bản, phòng? **Mặc định:** PK UUID; không coi `reference_no` là unique toàn đơn vị, hiển thị thông tin phòng + ngày để phân biệt; cảnh báo trùng.
- `H03`: Nếu nhập nhầm kết quả, được sửa/hủy/khôi phục thế nào? **Mặc định demo:** kết quả đã nộp là immutable, yêu cầu xác nhận trước khi nộp; không có UI xóa/sửa kết quả. Phải chốt chính sách correction trước pilot thật.
- `H04`: Hạn theo ngày hay ngày+giờ? **Mặc định:** nhập ngày, hết hạn lúc 23:59:59 giờ VN; cấu hình có thể đổi.
- `H05`: Lịch nhắc D-1, D-day, overdue mỗi sáng có phù hợp? **Mặc định:** trước hạn 1 ngày, ngày đến hạn, quá hạn mỗi ngày; không gửi nếu DONE.
- `H06`: Quá hạn gửi quản lý phòng chủ trì hay cả phòng của assignees? **Mặc định:** quản lý phòng chủ trì + assignees; lãnh đạo xem tổng hợp.
- `H07`: Reopen và tái nhắc? **Mặc định:** không reopen trong demo; cần SOP riêng nếu triển khai thật.
- `H08`: Watchers có tự theo dõi hồ sơ? **Mặc định:** chỉ creator/assigner/manager/leader thêm watcher và chỉ người trong đơn vị.

## E. Kịch bản nghiệp vụ chuẩn

1. Người giao đăng nhập → tạo hồ sơ bằng **số hiệu gốc**, phòng chủ trì, hạn xử lý → chọn 1..N assignees + watchers → Lưu.
2. Cán bộ đăng nhập → “Việc của tôi” → xem hồ sơ được giao, hạn còn lại, người giao và người theo dõi.
3. Web hiển thị việc sắp hết hạn; sau hạn chưa hoàn thành, tạo thông báo cho assignees và quản lý phòng chủ trì.
4. **Một** assignee nhập `KQ-2026-001` → Xác nhận → server ghi result + thời gian DB → hồ sơ DONE → không tạo thêm thông báo nhắc hạn mới.
5. Assignee khác nhập `KQ-2026-002` sau khi DONE → thêm result thứ hai, lịch sử đầy đủ, status vẫn DONE.
6. Trưởng phòng/lãnh đạo xem báo cáo đúng phạm vi; admin kỹ thuật không nhìn nội dung danh sách hồ sơ mặc định.

## F. Màn hình tối thiểu và UX

| # | Screen / route đề xuất | Nhiệm vụ người dùng |
|---|---|---|
| 1 | `/login/` | Đăng nhập dễ hiểu, trạng thái lỗi rõ |
| 2 | `/` | Tổng quan “Việc của tôi”, sắp hạn/quá hạn/đã xong, danh sách ưu tiên |
| 3 | `/ho-so/` | Tìm theo số hiệu, lọc phòng, trạng thái, hạn; chỉ hồ sơ được quyền |
| 4 | `/ho-so/tao/` | Form 1 màn hình: số hiệu, phòng, hạn, assignees, watchers |
| 5 | `/ho-so/<uuid>/` | Chi tiết: số hiệu, giao việc, hạn, kết quả, lịch sử; nút nộp rõ |
| 6 | `/thong-bao/` | Nhắc hạn web, đọc/chưa đọc; notification cũ sau DONE không còn pending |
| 7 | `/bao-cao/` | Số hồ sơ open/done/overdue theo phạm vi người xem |
| 8 | `/quan-tri/` | User, role, phòng ban và thành viên (chỉ admin kỹ thuật) |

Tất cả màn hình dùng desktop web responsive; không xây app điện thoại. Không đưa sidebar lồng nhiều tầng, sprint, Kanban, chat, AI, nhập văn bản dài. Form nộp kết quả chỉ có **số hiệu** và nút xác nhận; ngày nộp chỉ đọc và lấy từ DB. Dùng empty states, xác nhận trước khi nộp, font đủ lớn, nhãn tiếng Việt, hỗ trợ bàn phím.

## H. Yêu cầu mới 18/11/2026 — KPI có cấu hình (NEW REQUIREMENT)

Nguồn: `Book1.xlsx` Sheet1 A4:C17; plan `PLAN_CAND_NHAC_VIEC_KPI_CONFIG_MAIN`. Chi tiết thiết kế:
`docs/ADR-004-kpi-config-and-personal-scores.md`, `docs/ADR-005-periodic-plans.md`.

- `CONFIRMED` (Excel nói rõ): bỏ mục "Đang xử lý" và "Người theo dõi" khỏi UI; đổi nhãn chức
  năng; 5 tổ công tác mỗi tổ ≥1 tài khoản cán bộ; 2 tài khoản lãnh đạo; văn bản định kỳ tối
  đa 12 hạn/năm; nhiệm vụ khác tương đương văn bản; lãnh đạo xem điểm từng cán bộ, cán bộ chỉ
  xem điểm mình; chậm hạn và nhắc nhở bị trừ điểm; ví dụ tên "Công an phường A" chỉ là demo.
- `NEW REQUIREMENT`: phân hệ KPI có **màn hình cấu hình và quyền thao tác riêng** — bộ tiêu
  chí theo loại nhiệm vụ có version/trọng số, dải trừ chậm hạn và nhắc nhở, công thức gộp,
  vòng đời DRAFT→ACTIVE→SUPERSEDED, đánh giá/chốt/điều chỉnh điểm từng cán bộ.
- `OPEN DECISIONS` (D01–D17) — chưa chốt, giữ ở gate: định danh cán bộ trên tài khoản dùng
  chung; điểm cá nhân vs tổ; tiêu chí/trọng số/max_points; ngưỡng ngày 5/7; cách kết hợp hai
  khoản trừ; định nghĩa "1 lần nhắc"; nhiệm vụ chưa DONE cuối kỳ; công thức tổng KPI
  tháng/năm; tách trách nhiệm chấm/chốt; hạn hiệu lực sau đổi hạn; pin policy version theo
  kỳ; chứng cứ hoàn thành OTHER; xử lý watcher cũ; mức độ xóa "Nhóm hồ sơ"; officer xem điểm
  nháp; xếp loại điểm; KPI hồi tố. Excel `C15/C16` ghi trừ 25/50/75/100% nhưng các mốc 5 và
  7 giao nhau và không quy định công thức gộp — cấu hình mẫu lưu ở `DRAFT`, không activate.

## G. Điều kiện thành công

Một cán bộ không chuyên CNTT có thể: (1) tìm hồ sơ, (2) nộp một số hiệu, (3) thấy hồ sơ đã hoàn thành; người giao theo dõi được; quản lý nhận được thông báo khi quá hạn; mọi quyền và lịch sử được bảo toàn. **Đây là mục tiêu thiết kế**, phải kiểm chứng bằng usability test thực tế, không coi như đã đạt.
