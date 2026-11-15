# PLAN.md — Kế hoạch triển khai theo giá trị và nghiệm thu

**Triển khai tự động hóa bởi coding agent; không hứa deadline giả định.** Từng phase thực thi sau khi phase trước đạt gate; ưu tiên luồng người dùng chạy được thật thay vì tạo nhiều màn hình mockup. Mọi phase cần commit + commands test + PASS/FAIL/NOT RUN.

## Tổng quan phụ thuộc

`P0 (Repo+policy baseline) → P1 (Auth+Org+RBAC) → P2 (Records+Assignment) → P3 (Result+Atomic Close) → P4 (Notifications+Dashboard) → P5 (Polish+Security+Deploy) → P6 (Final acceptance)`

| Phase | Mục tiêu | Deliverables tối thiểu | Gate ra phase |
|---|---|---|---|
| P0 | Khóa stack, dựng dự án | Django 5.2, Postgres, Templates/HTMX/Tailwind, Docker Compose dev, custom User, CI/test scaffolding | `runserver`/Compose lên, migrations chạy trên PG, `/login/` render, lệnh test hoạt động |
| P1 | Identity, org, policy | Unit, Department, custom User, roles, login/logout, scoped query, admin user/department, seed giả lập | IDOR + unit isolation + sysadmin-not-business access tests pass |
| P2 | Hồ sơ & giao việc | WorkRecord/Assignee/Watcher, create/list/detail, assign/manage due, audit, filter/search | Một hồ sơ nhiều assignees, không subtask, quyền đúng, create/update log đầy đủ |
| P3 | Nộp & tự hoàn thành | Form nộp mã, transaction, unique per record normalized code, DB time, DONE, additional refs, audit | Two concurrent submitters: 2 results + 1 DONE event; repeated POST không nhân đôi; viewer bị cấm |
| P4 | Nhắc hạn & quan sát | Scheduled reminders, inbox thông báo, overdue manager, dashboard scope + report | Có reminder trước hạn/đến hạn/quá hạn; không reminder sau DONE; không leak báo cáo |
| P5 | Tối giản UX, security, vận hành | Responsive VN UI, validation/errors, demo seed, deployment/backup/restore docs, HTTPS config | Usability smoke, Django deploy checks, dependency/security checks, restore thử đạt |
| P6 | Nghiệm thu cuối & handoff | Test report, screenshots thật, demo walkthrough, risks/known limitations, version/commit | Toàn bộ MUST `ACCEPTANCE.md` PASS hoặc release BLOCKED có lý do |

## P0: Project foundation

- [ ] Kiểm tra repo hiện có, tạo nhánh mới nếu phù hợp; không reset/overwrite thay đổi chưa commit.
- [ ] Python 3.12, Django 5.2 LTS (latest patched 5.2.x), psycopg, PostgreSQL 16+, `django-htmx`, Tailwind build pipeline (static assets local); chọn exact versions lúc build và commit lock.
- [ ] Django custom User `AUTH_USER_MODEL` tạo **trước** migration đầu tiên; settings split dev/demo, timezone UTC, locale VI.
- [ ] `compose.yaml` dev cho app+postgres (scheduler chưa cần), health checks và `.env.example` không chứa secret thật.
- [ ] Tạo static HTML skeleton tiếng Việt, `layout.html`, test project boot.
- [ ] Viết ADR nếu có xung đột stack với repo đang có; không đổi stack đã chốt.

**Gate P0:** migration thành công PostgreSQL, app boot, test command trả kết quả, screenshot login (chưa cần auth đầy đủ).

## P1: Identity + unit/department + policy

- [ ] Models Unit, Department, User; seed 2 units x 2 departments, officers/managers/leader/admin bằng người giả lập.
- [ ] Login/logout, secure session, password policy, login throttling.
- [ ] Một module `policies.py`/`querysets.py` làm source of truth; sẵn `visible_records_queryset` hoặc equivalent.
- [ ] Tech sysadmin quản lý users/depts nhưng không xem hồ sơ nghiệp vụ.
- [ ] Bắt unit mismatch ở tất cả foreign keys, forms, services (không chỉ UI dropdown).
- [ ] Tests login/role changes/multi-unit inaccessible/manager scope.

**Gate P1:** negative authorization suite pass; không lộ record từ unit khác qua URL.

## P2: Records CRUD giới hạn + assignment

- [ ] Models WorkRecord, RecordAssignee, RecordWatcher, AuditEvent; migrations và indexes.
- [ ] Tạo hồ sơ: số hiệu gốc + phòng chủ trì + deadline + >=1 assignee + watchers tùy chọn. `assigner` mặc định creator; server validates eligibility.
- [ ] Danh sách/tra cứu số hiệu, bộ lọc phạm vi; detail hiển thị người giao, assignees, watchers, deadline, history.
- [ ] Update assignees/watchers/deadline khi OPEN và actor đủ quyền; audit trước/sau; không tạo subtask.
- [ ] UX cho cán bộ không chuyên IT: một form ngắn, thông báo lỗi rõ, tìm kiếm nổi bật.

**Gate P2:** 1 record có 3 assignees, 2 watchers, không thể xem/sửa/giao người ngoài scope; lịch sử chính xác.

## P3: Result references + concurrency

- [ ] Model ResultReference; normalization và unique constraint `(record, normalized_code)`.
- [ ] Form `Nộp số hiệu kết quả` chỉ nhận mã text; khối xác nhận tránh nhập nhầm, không file upload.
- [ ] Service atomic lock record, check active assignee under lock, insert result, persist DB timestamp, auto-DONE first result, audit 2 events, resolve active reminder.
- [ ] DONE vẫn nhận thêm số hiệu (nếu active assignee), không đổi original completion timestamp.
- [ ] Các tests: submit từ watcher/admin/removed assignee denied; simultaneous 2 submits; duplicate code; POST retry; record DONE invariant; DB timestamps.

**Gate P3:** chạy test PostgreSQL thật, 2 separate connections và kiểm tra đúng 1 `record.completed`, 2 result (nếu 2 mã khác nhau); không có duplicate do retry.

## P4: Notifications + reports

- [ ] Derived overdue (không tạo status riêng); management command idempotent để tạo reminder.
- [ ] Notification web; nhận nhắc hạn và quá hạn; người quản lý phòng chủ trì thấy escalations; chỉ hiển thị trong scope.
- [ ] `DONE` giải quyết notification chờ xử lý và không tạo reminder mới, kể cả scheduler/submit race.
- [ ] Dashboard của tôi, phòng, đơn vị + tổng hợp OPEN/DONE/OVERDUE đúng scope.
- [ ] Tests dedupe, boundary, no-reminder-after-close, scheduler idempotency.

**Gate P4:** chạy 2 lần command không double; quá hạn người xử lý + manager; status DONE không còn active deadline reminder.

## P5: Demo hoàn chỉnh + hardening

- [ ] CSS local, UI ít thao tác: login → của tôi → detail → nộp → DONE.
- [ ] Form accessible labels, keyboard navigation, readable error/success states; responsive web.
- [ ] Seed demo giả lập có 2 units/4 departments, >8 accounts giả lập, record đang mở/sắp hạn/quá hạn/đã đóng.
- [ ] Deployment Docker Compose, reverse proxy HTTPS hoặc cấu hình để host dùng TLS, không expose PostgreSQL; secure cookies/headers/DEBUG off.
- [ ] Backup + restore drill; `python manage.py check --deploy`; dependency CVE scan; verify `.env` không commit.
- [ ] README_RUN.md: run/migrate/seed/admin/cron/backup/restore/tests.

**Gate P5:** demo từ trình duyệt trên dữ liệu giả; setup sạch tái tạo được; bộ kiểm tra an ninh cơ bản đạt.

## P6: Independent acceptance / council checkpoint

- [ ] Chạy lại tất cả `ACCEPTANCE.md`, đính kèm log/command/commit; ghi những test `NOT RUN`.
- [ ] Council mô phỏng 5 vai: nghiệp vụ, UX, backend, bảo mật, vận hành; ghi **finding** chứ không tự ghi pass cho chức năng chưa chạy.
- [ ] Kiểm tra 3–5 phút demo walk-through và bằng chứng tính đúng trên PG.
- [ ] Kết luận `READY_FOR_CONTROLLED_DEMO` hoặc `BLOCKED` (không tự tuyên bố đủ điều kiện vận hành nghiệp vụ thật).

## Dừng hoặc thu hẹp scope khi

- Phase P3 race/atomic close chưa pass → không làm cosmetic UI thay thế.
- P1 permission leakage → không publish bản demo.
- Không có quyền deploy/approval hoặc không rõ dữ liệu → chỉ demo local với synthetic.
- User yêu cầu sửa chính sách giữa chừng → ADR mới + policy matrix tests trước code tiếp.

## Ngoài MVP / backlog sau demo

SSO, API integration, import Excel, lịch sử correction/reopen, multi-unit provisioning, SLA tùy biến, mobile native, realtime push, digital signatures, workflow engine, AI/OCR. Không triển khai trừ khi có yêu cầu và authorization cụ thể.
