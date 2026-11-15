# CAND PocketOps — Django Agent Starter v2.0

**Loại tài liệu:** Bộ đặc tả tối thiểu để coding agent triển khai bản demo; **không chứa mã nguồn ứng dụng hoàn chỉnh**.  
**Ngày khóa kiến trúc:** 15/11/2026. **Ngôn ngữ UI:** tiếng Việt. **Môi trường:** web-only, truy cập mạng được phép trong demo có kiểm soát.

## 1. Quyết định cuối cùng

- **Không fork Plane, Vikunja, OpenProject hay Frappe.** Dùng framework, thư viện OSS và tự viết logic nghiệp vụ đặc thù.
- **Backend + UI:** Python 3.12 + Django **5.2 LTS** (luôn chọn bản vá ổn định mới nhất trong nhánh 5.2 tại thời điểm cài). Django Templates + Django Forms + HTMX + Tailwind CSS biên dịch thành static assets lưu cục bộ.
- **Database:** PostgreSQL 16+; **deploy:** Docker Compose, một Django app modular monolith, một PostgreSQL, reverse proxy HTTPS và một tác vụ nhắc hạn theo lịch. Không cần React SPA, Celery, Redis, Kafka, microservices, WebSocket ở MVP.
- **Mục tiêu:** quản lý hồ sơ công việc theo số hiệu (không quản lý nội dung hồ sơ). Có người giao, nhiều người xử lý, watchers, hạn xử lý, số hiệu kết quả, audit và thông báo trong web.
- **Cốt lõi:** khi bất kỳ assignee đang có quyền nộp số hiệu kết quả hợp lệ đầu tiên, **toàn bộ hồ sơ tự đóng ngay**; ngừng tạo nhắc hạn mới; vẫn có thể bổ sung số hiệu khác sau đó.
- **Không dữ liệu thật:** chỉ người dùng, phòng ban và hồ sơ **giả lập**. Không kết nối hệ thống công an, dữ liệu công dân, tài liệu mật hay dữ liệu điều tra. Không dùng biểu trưng cơ quan chính thức nếu chưa được phép.

## 2. Sáu file — đúng thứ tự đọc

| File | Chức năng | Khi nào đọc |
|---|---|---|
| `README.md` | Tổng quan, prompt khởi động, quyết định | Đầu tiên |
| `AGENTS.md` | Quy tắc bắt buộc cho coding agent | Trước bất kỳ thay đổi code nào |
| `CONTEXT.md` | Yêu cầu đã chốt, quy trình, phân quyền, UI, mặc định chưa chốt | Trước thiết kế model |
| `ARCHITECTURE.md` | Hội đồng phản biện mô phỏng, ADR, kiến trúc, data contract, security | Trước code |
| `PLAN.md` | Trình tự triển khai, tasks, dependencies, gates | Trong mỗi phase |
| `ACCEPTANCE.md` | Cases nghiệm thu, thử race conditions, demo, release checklist | Viết test trước và sau từng phase |

## 3. Bắt đầu với coding agent

1. Tạo một repository mới hoặc chọn thư mục làm việc trống, giải nén 6 file này **vào root của repository**. Nếu repo đã có code, trước tiên yêu cầu agent rà soát và bảo toàn trạng thái Git.
2. Copy prompt dưới đây vào coding agent; yêu cầu tạo/commit code và ghi minh chứng test, **không chỉ tạo mockup**.
3. Agent thực hiện `P0` rồi `P1` ... `P6` theo `PLAN.md`; không xây tích hợp hệ thống ngoài MVP.
4. Mọi thay đổi chính sách phải cập nhật `CONTEXT.md`/ADR trước khi đổi code; các điểm chưa xác nhận phải được ghi là **giả định của demo**.

### Prompt khởi động (copy nguyên khối)

```text
Bạn là lead engineer triển khai CAND PocketOps Django web demo.
Đọc đủ README.md, AGENTS.md, CONTEXT.md, ARCHITECTURE.md, PLAN.md, ACCEPTANCE.md theo thứ tự.
Kiến trúc đã CHỐT: Python 3.12, Django 5.2 LTS, Django Templates + HTMX + Tailwind CSS, PostgreSQL 16+, Docker Compose. KHÔNG fork Plane/Vikunja, không đổi sang React/Next.js/Frappe, không bổ sung microservices/AI.
Đầu tiên kiểm tra repo, trạng thái Git và môi trường. Thực hiện P0, ghi rủi ro/giả định, sau đó code theo P1→P6. Tạo migration/model/form/view/template/service/policy/test có thật; UI mặc định tiếng Việt và thân thiện với cán bộ không chuyên CNTT.
Chỉ dùng dữ liệu giả lập; không tự động deploy lên internet, không nối hệ thống thật, không lấy thông tin người dân. Kiểm tra RBAC + phạm vi đơn vị/phòng ban/từng hồ sơ trên server cho mọi view, mutation và báo cáo.
Đặc biệt: nộp 1 số hiệu kết quả hợp lệ bởi 1 assignee => đóng cả hồ sơ atomically, không tạo reminder mới. Nhiều assignees có thể nộp thêm số hiệu ngay cả khi đã đóng; transaction phải xử lý đồng thời, chỉ một event chuyển trạng thái DONE. Timestamps lấy từ database, không từ browser. Audit phải lưu thay đổi.
Mỗi phase xuất: tóm tắt diff, lệnh test đã chạy, kết quả PASS/FAIL/NOT RUN, hash commit và blockers. Chỉ đánh DONE khi thỏa ACCEPTANCE.md; nếu không chạy được, nói rõ chứ không khẳng định đã pass.
Bắt đầu ngay với P0, không hỏi lại các quyết định đã khóa trong tài liệu.
```

## 4. Cơ sở công nghệ (nguồn chính thức)

- Django 5.2 LTS: https://docs.djangoproject.com/en/5.2/releases/5.2/
- Lịch hỗ trợ: https://www.djangoproject.com/download/
- Transactions: https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- `select_for_update`: https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update
- Django security deployment: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- django-htmx / CSRF: https://django-htmx.readthedocs.io/en/stable/installation.html

## 5. Ranh giới quyết định

Các quyền giao **liên phòng của cán bộ**, cách xử lý **số hiệu nhập sai**, và chuẩn **số hiệu trùng** chưa được người đặt yêu cầu phê duyệt nghiệp vụ. `CONTEXT.md` có mặc định demo theo nguyên tắc ít quyền nhất; **không được trình bày như quy chế thực tế**.
