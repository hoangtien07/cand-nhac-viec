# CAND PocketOps — Home UI Design Specification v1.0

> **Loại tài liệu:** thiết kế mục tiêu cho màn trang chủ đã được owner duyệt; dùng kèm `IMPLEMENTATION_PLAN.md` và `reference/home-approved.png`.
>
> **Mã nguồn tham chiếu:** `hoangtien07/cand-nhac-viec`, `main` commit `3b183d3e7a901a3cf84a239728094c05e540fbc7`, kiểm tra ngày 15/11/2026. Nếu HEAD đã thay đổi, coding agent phải rebase/đối chiếu trước khi bắt đầu.
>
> **Trạng thái:** design target đã được owner chốt qua ảnh, các *giả định nghiệp vụ bổ sung* bên dưới là quyết định kỹ thuật của kế hoạch, không mặc nhiên là chính sách ngành.

## 1. Mục tiêu, phạm vi, giới hạn

### Mục tiêu
- Chuyển trang chủ từ 5 khối danh sách đơn giản thành một **workspace quản lý công việc rõ ràng**, khớp thứ bậc thị giác của ảnh: header navy → sidebar trắng → vùng nội dung → KPI và bảng chính → lịch và nhắc việc bên phải → shortcut → footer ngữ cảnh.
- Cán bộ không chuyên IT nhìn thấy việc cần làm, tìm nhanh bằng số hiệu, mở hồ sơ, xem hạn và nộp kết quả với tối đa vài thao tác.
- Dùng component UI chia sẻ cho **các màn tiếp theo**: list, detail, create, notifications, reports và quản trị.
- Dữ liệu KPI, bảng, lịch và thông báo **lấy từ PostgreSQL qua policy hiện có**, không render số giả theo screenshot.

### Không làm trong đợt này
- Không thay Django Templates/HTMX/Tailwind bằng React, Vue hoặc SPA khác.
- Không chỉnh `submit_result_reference`, khóa PostgreSQL, audit, scheduler nhắc hạn, quyền người dùng chỉ vì thay giao diện.
- Không thêm file attachment, subtasks, workflow duyệt, email/SMS/push, AI, API tích hợp.
- Không sử dụng logo chính thức mới nếu chưa được phép; tài sản brand trong ảnh là **tài liệu tham khảo**, không phải giấy phép sử dụng công khai.
- Không thêm trường mô tả hồ sơ nhạy cảm/"Trích yếu công việc" chỉ để giống mockup.

## 2. Ràng buộc dữ liệu quan trọng — ảnh minh họa vs hệ thống thật

1. `apps/records/models.py::WorkRecord` hiện chỉ lưu `reference_no`, `owner_department`, `assigner`, `due_at`, status, timestamp; **không có `title`, `description` hay `trich_yeu`**.
2. Vì vậy cột trong ảnh ghi **“Trích yếu công việc”** chỉ được coi là **minh họa thị giác**. Trong phiên bản xây ngay: **đổi thành “Thông tin hồ sơ”** và hiển thị metadata thực có quyền truy cập, ví dụ tên người giao, hoặc bỏ cột khi thiếu không gian. KHÔNG bịa nội dung công việc hoặc hardcode mã → mô tả. Chỉ bổ sung trường mới nếu chủ dự án phê duyệt một thay đổi nghiệp vụ riêng và chính sách phân loại thông tin.
3. `WorkRecord` không có `work_year`. **Quy ước UI v1**: *Năm làm việc = năm của `created_at` theo `Asia/Ho_Chi_Minh`*. Bộ lọc năm ở footer phải lọc bằng khoảng thời gian `created_at` `[01/01 năm, 01/01 năm+1)` (timezone aware). Không đoán năm theo `reference_no`, `due_at`, `completed_at`; không thay đổi model, không migration. Nếu sau này có hồ sơ xuyên niên độ, lập ADR bổ sung `work_year` rõ nghĩa.
4. `User` có đúng một `unit` và `department`. Footer **“Đơn vị công tác”** hiển thị `department.name` (kèm `unit.name` trong tooltip/context khi cần); không là menu đổi tenant/phòng ban. Chỉ hiển thị mũi tên dropdown khi thực sự có lựa chọn được backend cho phép.
5. Màn `Công việc của tôi` gồm **những hồ sơ người dùng đang là assignee còn hiệu lực**, lấy từ `policies.visible_records_queryset(user)` rồi mới lọc người dùng, năm và tab. Các hồ sơ do tôi tạo/giao nhưng không là assignee có thể truy cập từ Danh sách hồ sơ theo quyền hiện có, không trộn vào số KPI “của tôi”.
6. Ảnh ví dụ có KPI 12/18/47/126 và lời nhắc ngày 12/11/2026: **không hardcode**. Số liệu theo đúng `db_now()` và bộ lọc `active_work_year`, permission của người đăng nhập.
7. Các menu `Quản trị`, `Người dùng`, `Phòng ban`, `Vai trò & quyền` chỉ xuất hiện cho vai trò có quyền *theo `accounts` hiện tại*. Chụp ảnh một lãnh đạo có các menu quản trị **không đồng nghĩa** mọi lãnh đạo có quyền quản trị kỹ thuật.

## 3. Information architecture — bố cục đã chốt

```text
┌────────────────────────────────── HEADER navy 72px ──────────────────────────────────────┐
│ [Brand | DEMO]   [Giải thích ngắn]                          [Bell] [?] [Avatar | User]    │
├──────── SIDEBAR 272px ──────┬─────────────────────────────┬──────────────────────────────┤
│ Trang chủ (active)          │ Xin chào, <tên>             │ Lịch & Nhắc việc             │
│ Hồ sơ công việc             │ [KPI x4 / responsive]       │ [Lịch tháng và ngày có việc] │
│ Tạo hồ sơ                   │                             │                              │
│ Báo cáo – Thống kê          │ Công việc của tôi           │ Nhắc việc hôm nay (≤3)       │
│ Thông báo [badge]           │ Tabs                        │ → Mở hồ sơ                  │
│ [Quản trị* theo role]       │ Search + bộ lọc            │                              │
│   Người dùng*              │ Bảng record (4–10 hàng)     │                              │
│   Phòng ban*               │ [Empty/loading/pagination] │                              │
│   Vai trò & quyền*         ├─────────────────────────────┴──────────────────────────────┤
│   Cấu hình hệ thống*       │ Chức năng nhanh (chỉ các action được phép)                │
├─────────────────────────────┴────────────────────────────────────────────────────────────┤
│ FOOTER: Đơn vị công tác [read-only] | Năm làm việc [select]  | Demo/synthetic disclaimer    │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Thứ bậc thị giác
- **Cấp 1:** top header chứa thương hiệu, thông báo và tài khoản đăng nhập.
- **Cấp 2:** side navigation xác định màn hiện tại; menu active nền đỏ đậm, chữ trắng.
- **Cấp 3:** khu vực chính có heading, mô tả một câu, KPI 4 khối trạng thái.
- **Cấp 4:** vùng `Công việc của tôi` chiếm diện tích lớn nhất; tìm kiếm **bên trong card, gần bảng**, không phải header toàn cục.
- **Cấp 5:** cột phụ 350px với lịch tháng + tối đa 3 nhắc việc; không cạnh tranh với bảng.
- **Cấp 6:** shortcuts dưới bảng, chỉ chứa đường dẫn có ý nghĩa và có quyền thực hiện.

## 4. Design tokens (giá trị khởi đầu gần screenshot, điều chỉnh theo visual QA)

| Token | Giá trị | Sử dụng |
|---|---|---|
| `--po-header` | `#132F67` | Header/navy |
| `--po-header-deep` | `#0D2250` | Header gradient endpoint |
| `--po-nav-active` | `#B80E2A` | Sidebar active, quan trọng |
| `--po-nav-active-hover` | `#9E0923` | Hover nav |
| `--po-foreground` | `#17274F` | Văn bản chính |
| `--po-muted` | `#52617B` | Văn bản phụ |
| `--po-page` | `#F6F8FC` | Nền toàn trang |
| `--po-surface` | `#FFFFFF` | Card/table |
| `--po-border` | `#D8E1F0` | Borders |
| `--po-info` | `#1565DB` | Link, processing |
| `--po-danger` | `#C32234` | Quá hạn |
| `--po-warning` | `#B66B00` | Sắp hạn |
| `--po-success` | `#187A3E` | Đã hoàn thành |
| `--po-radius-card` | `12px` | Card |
| `--po-radius-control` | `8px` | Input/button |
| `--po-shadow-card` | `0 2px 10px rgb(16 40 80 / .05)` | Bề mặt nâng |
| `--po-header-height` | `72px` | Desktop header |
| `--po-sidebar-width` | `272px` | Desktop side |
| `--po-aside-width` | `352px` | Desktop right rail |
| `--po-footer-height` | `56px` | Desktop footer |

- Font: ưu tiên hệ thống `system-ui` với fallback tiếng Việt; nếu bổ sung font thì đóng gói local (không CDN), kiểm tra dấu tiếng Việt. Cỡ chữ thân 15–16px; nhãn phụ ≥13px; heading chính 26–30px; touch target ≥40px; khoảng cách trên grid 4/8/12/16/24px.
- Trạng thái không chỉ phân biệt bằng màu: luôn có chữ “Quá hạn”, “Sắp đến hạn”, “Đang xử lý”, “Đã hoàn thành”. Giữ tương phản WCAG AA 4.5:1 cho văn bản thường.
- Icon thống nhất nét outline, stroke 1.75–2; SVG local/sprite, không emoji không CDN. Không nhập cả bộ icon JS nếu chỉ cần ~20 biểu tượng.
- Primary action: trong ảnh phần nội dung chủ yếu tương tác bằng đỏ/nền trắng; dùng đỏ cho active nav và một CTA chính, không biến toàn bộ link thành đỏ. Nút submit kết quả ở màn chi tiết cần nổi bật nhưng không lệch palette.
- Tránh hiệu ứng glassmorphism, gradient màu lớn, hoạt ảnh phi nghiệp vụ và bảng nhiều khối gây rối.

## 5. Component contract dùng chung (Django include / template tags / CSS classes)

### App shell
- `templates/base.html`: tiếp tục là application shell duy nhất cho mọi màn, dùng includes cho header/sidebar/footer và giữ block `content` tương thích; phân định business vs technical admin. Không cần tạo `layouts/app.html` chỉ để bọc thêm một tầng không có giá trị.
- `templates/components/_header.html`: brand, note, `notifications` unread badge, help route/tooltip, user dropdown (profile info + POST logout). Chỉ dùng dữ liệu `request.user`; user dropdown không lấy tên từ fixtures.
- `templates/components/_sidebar.html`: `nav_key`/request.resolver_match nhận diện mục active; links qua `{% url %}`; ẩn link không có quyền.
- `templates/components/_footer.html`: `unit`, `department` đang đăng nhập + `work_year` selector + synthetic disclaimer; nếu quyền đổi unit không tồn tại, chỉ hiển thị read-only.
- `templates/components/_messages.html`: Django messages; success/error/info, focus và `role=alert/status`.
- `templates/components/_icons.html` hoặc `static/icons/*.svg`: icon SVG local.

### Trình bày nghiệp vụ
- `templates/components/_kpi_card.html`: props `label`, `count`, `tone`, `icon`, `href`; link chỉ tới tab hợp lệ; zero vẫn hiển thị `0`.
- `templates/components/_status_badge.html`: wrapper **reuse** logic hiện có ở `templates/records/_state_badge.html`, không sao chép điều kiện deadline ở nhiều nơi.
- `templates/components/_filter_bar.html`: field search, select department, status; GET preservers year/tab, CSRF không cần với GET; có nút reset.
- `templates/components/_empty_state.html`: text + CTA hợp lệ.
- `templates/components/_record_table.html`: markup `<table>`, `<caption class="sr-only">`, `<thead>`, body, click record link, row hover/focus, no invented data.
- `templates/components/_pagination.html`: giữ query params year/tab/q bằng `QueryDict` safe serialization trên server, không build URL thủ công lỗi encoding.
- `templates/components/_calendar.html`: dùng Python `calendar` + deadline của các record thuộc scope; event markers có alt/text; month navigation có năm.
- `templates/components/_reminder_list.html`: tối đa 3 actionable notifications của người hiện tại, nội dung tối thiểu, links theo policy.
- `templates/components/_quick_actions.html`: create, list, submit flow, reports, user admin, settings; chỉ có phần được backend cấp phép; **shortcut Nộp kết quả → danh sách việc được giao đang mở**, không nộp khi chưa chọn record.
- `templates/components/_skeleton.html`: *chỉ nếu thực sự có HTMX loading*: spinner/skeleton đơn giản, tránh flash.

**Quy ước gọi:** Component có responsibility duy nhất; template chỉ render dữ liệu và link; không thực thi business policy, không query DB trong template. Có thể gộp component nhỏ nếu việc tách làm tăng template include không cần thiết.

## 6. Quy tắc dữ liệu của trang chủ

### Cards và tabs
Tất cả dữ liệu đi từ `policies.visible_records_queryset(user)` → lọc `assignees__user=user`, `assignees__is_active=True` → lọc **năm tạo hồ sơ đã chọn**. Sau đó phân lớp loại trừ nhau:
- `overdue`: `OPEN AND due_at < db_now()`.
- `due_soon`: `OPEN AND now <= due_at < due_soon_cutoff(now)` theo setting hiện có.
- `processing`: `OPEN` nhưng không `overdue`, không `due_soon`.
- `done`: `DONE` (không bị tính quá hạn dù due_at đã qua).
- `all`: union 4 tập trên (không tính trùng). KPI counts gắn với 4 tập, không pha số liệu toàn đơn vị với số liệu cá nhân.

Tab `Tất cả` có thể là mặc định, tab khác lọc dòng; KPI và số ở tabs phải khớp cùng snapshot/truy vấn. Table order: overdue trước, due soon tiếp, processing tiếp, done cuối; từng nhóm sắp `due_at` tăng/`completed_at` giảm phù hợp. Không phụ thuộc format số hiệu để sort thời gian.

### Bảng công việc
- Các trường có thật: `Số hiệu` (link), `Thông tin hồ sơ` (người giao hoặc nhãn nguồn, không mô tả nhạy cảm), `Phòng ban`, `Hạn xử lý`, `Trạng thái`, optional `Người xử lý` nếu nhiều assignees (sử dụng initials avatar). Checkbox chỉ xuất hiện khi có hành động hàng loạt thực sự được triển khai; mặc định **không hiển thị checkbox vô tác dụng**.
- Tìm kiếm: mã số hiệu gốc hoặc số hiệu kết quả (reuse code search normalization) + bộ lọc có quyền. Search nằm **dưới tabs, sát bảng**.
- Có 5–10 rows/page, pagination thật; zero matches có empty state, xóa lọc, không để ô trắng giả.
- Nếu text quá dài, truncate + `title`/tooltip đầy đủ, không overflow; các nội dung thuộc phạm vi được phép mới được render.

### Lịch và nhắc việc
- Tháng hiện tại theo giờ VN; khi năm làm việc khác năm hiện tại, chọn cùng tháng theo năm đang hiển thị; không dùng ngày tĩnh của ảnh.
- Số marker/ngày lấy từ deadline của hồ sơ đã được giao, theo scope/year. Không tạo calendar event DB riêng, không làm drag/drop.
- Nhắc việc hôm nay dùng `visible_notifications` + `actionable`, nhận theo người, và nếu cần lọc theo `record.created_at` năm đã chọn. Không tiết lộ notification nếu người dùng không còn quyền xem record.
- Nhắc hạn sau DONE đã được backend chặn; UI không được hiển thị như “cần xử lý” sau khi đóng.

### Footer
- `Đơn vị công tác: {{ user.department.name }}` nếu có, hoặc `{{ user.unit.name }}`; tên unit đầy đủ xem khi cần.
- `Năm làm việc: YYYY`: selector POST CSRF `records:set_work_year`, lưu `request.session['pocketops_work_year']`. Năm hợp lệ trong cửa sổ kiểm soát `[năm hiện tại - 5, năm hiện tại + 1]`; cấm injection/string lạ. Default năm VN hiện tại; sau đổi trở lại dashboard. `get_active_work_year(request)` và `filter_created_in_work_year(qs, year)` dùng chung các màn dashboard, record list và report. Do not filter other users or other units after permission boundary incorrectly.
- Do **not** đổi `request.user.unit`/department từ footer; year selection không có tác dụng phân quyền.

## 7. Responsive và tương tác

| Viewport | Bố cục |
|---|---|
| ≥1440px | Sidebar 272px, main fluid, right rail 352px, bảng chiếm ưu tiên |
| 1024–1439px | Sidebar thu gọn hoặc 224px, rail 300px, card KPI 2×2 nếu cần; table có scroll ngang được thông báo |
| 768–1023px | Sidebar thành drawer, right rail xuống dưới bảng, KPI 2×2 |
| 390–767px | Header 56–64px, drawer, KPI 2×2, bảng chuyển responsive rows hoặc scroll dễ nhận biết, footer không che nút |

- Không dùng `position:fixed` cho footer trên màn nhỏ nếu che bảng; desktop có thể sticky/bottom theo shell. Sidebar và header chỉ có **một nguồn cấu hình**.
- HTMX GET tab/filter phải cập nhật bảng/count cần thiết, phản hồi lỗi có thông báo; `hx-push-url` giữ lịch sử và back/forward. Full GET và HTMX GET nhất quán. Không biến filters thành mutation.
- Dropdown thông báo/tài khoản đóng bằng ESC, hỗ trợ keyboard, `aria-expanded`, click-outside (không đòi thư viện mới nếu HTML/details đáp ứng).
- Form year là POST CSRF; mọi action tạo/nộp/đổi hạn tiếp tục POST hiện có. Header logout POST hiện có phải giữ.

## 8. Biên giới an toàn và khả năng truy cập

- Không dùng icon hình ảnh của lực lượng nếu không được phép sử dụng; brand placeholder cho môi trường chưa có duyệt. Không suy quyền từ việc ảnh có logo.
- Hình được duyệt là **visual north star**, không phải schema hay policy spec. Giữ `AGENTS.md`, `CONTEXT.md`, `ARCHITECTURE.md`, `ACCEPTANCE.md` làm nguồn nghiệp vụ.
- Template escaping mặc định; tránh `|safe` với dữ liệu user; GET/HTMX dùng queryset scoped; không đưa toàn bộ record IDs ra HTML một cách không cần thiết.
- UI release không phá keyboard skip link, tab/focus order, heading levels, visible error messages; không chỉ dùng màu diễn tả trạng thái.

## 9. Tiêu chí nghiệm thu thiết kế

1. Ảnh thật ở 1672×941 có đúng kiến trúc phân vùng, typography, thanh header user bên phải, search sát bảng, footer unit/year. Sai khác pixel so với ảnh AI là chấp nhận, nhưng **không chấp nhận** sai hierarchy hoặc không đúng dữ liệu.
2. `Trang chủ` active ở sidebar; admin menu chỉ khi có quyền; user dropdown có POST logout; unread badge từ query.
3. 4 KPI + 5 tabs đúng scope và cùng năm; không hardcode một con số; không tạo trường nhạy cảm.
4. Bộ lọc search, trạng thái, năm tác động thật; URL/back/forward/HTMX hoạt động.
5. 3 nhắc việc là recipient-safe; click đi tới record có quyền, records đã DONE không còn actionable reminder.
6. Mobile 390px và desktop 1280px/1672px không che điều khiển, không tràn ngang toàn trang, bảng vẫn dùng được.
7. Existing authz/concurrency/submit/reminders tests vẫn PASS; E2E cập nhật bám testid/role thay vì cấu trúc markup cũ.
8. Logo, nội dung sample và tài liệu phải dùng dữ liệu giả, không tuyên bố được tích hợp với hệ thống chính thức.
