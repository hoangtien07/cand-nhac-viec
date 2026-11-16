# ADR-003: Bổ sung phương án demo Vercel và Neon

Trạng thái: được yêu cầu cho demo dữ liệu giả lập; không thay thế phương án Compose.

Django chạy trên Vercel, PostgreSQL trên Neon. GitHub Actions chạy management command nhắc hạn một lần mỗi ngày, thay cho scheduler mỗi giờ của Compose. Chọn cách chạy lệnh trực tiếp vì Vercel Cron gửi GET, trong khi dự án yêu cầu mutation HTTP dùng POST và CSRF. Lịch có thể trễ hoặc bị bỏ và cần theo dõi, chạy bù. Không có endpoint nhắc hạn mới.

Neon dùng endpoint mạng bên ngoài, khác triển khai nội bộ của ADR-001. Trước khi đưa demo lên Internet, owner cần xác nhận ranh giới mạng, hạn chế truy cập database và chấp nhận các điều kiện release trong ARCHITECTURE.md; cấu hình này không tự chứng minh các điều kiện đó đã được đáp ứng. Chỉ dùng dữ liệu giả lập. PostgreSQL transaction, phân quyền và audit không thay đổi. Không chạy đồng thời scheduler Compose và lịch GitHub cho cùng database khi vận hành demo.
