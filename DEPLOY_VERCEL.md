# Demo Vercel Hobby + Neon Free

Chỉ dùng dữ liệu giả lập. Đây là cấu hình bổ sung; Compose trong README_RUN.md vẫn dùng được. Không đưa thông tin đăng nhập, URL database hay secret vào Git, log hoặc trao đổi công khai. Trước khi phát hành, owner cần xác nhận điều kiện mạng và release của ARCHITECTURE.md: Neon có endpoint mạng bên ngoài, nên cần đánh giá/hạn chế truy cập và không coi cấu hình này tự động đáp ứng điều kiện database không public.

## 1. Neon

Tạo project PostgreSQL 16+, chọn region gần Vercel. Từ Connect lấy database, user, password và hostname. Dùng hostname pooled cho web và hostname direct cho migration, seed và job. Kết nối bắt buộc TLS, xác minh chứng chỉ bằng trust store hệ thống (`sslrootcert=system`, cần libpq 16+). Tách database demo, preview và local; đừng kết nối preview vào database demo chính. Neon Free có thể scale về zero và làm chậm kết nối đầu tiên.

## 2. Cấu hình Vercel

Import repo, chọn root dự án, bật framework Django tự phát hiện. Trong Settings > Environment Variables, đặt cho Production:

| Tên | Giá trị |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.vercel` |
| `DJANGO_SECRET_KEY` | Giá trị ngẫu nhiên mạnh, riêng môi trường |
| `DJANGO_ALLOWED_HOSTS` | Hostname chính xác, không gồm scheme; nhiều tên cách nhau bằng dấu phẩy |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origin HTTPS đầy đủ, nhiều origin cách nhau bằng dấu phẩy |
| `POSTGRES_HOST` | Hostname pooled từ Neon, không chứa user/password/port |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Thông tin Neon tương ứng |
| `POSTGRES_PORT` | `5432` |

Các biến phải có cả lúc build lẫn runtime. Không bật Preview trỏ vào database demo chính; cấu hình môi trường preview riêng nếu cần. Dùng hostname ổn định cụ thể cho ALLOWED_HOSTS và CSRF, không mở wildcard tùy tiện. Biến thay đổi cần redeploy. Vercel nhận diện `manage.py` và `STATIC_ROOT`; kiểm tra build/collectstatic và asset thực tế sau deploy. Không chạy migration hoặc seed trong build hay function.

Tạo secret tại máy riêng, ví dụ `uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`; nhập thẳng vào Vercel/GitHub, không lưu kết quả trong repo. Vercel Hobby chỉ dành cho mục đích cá nhân hoặc phi thương mại; kiểm tra điều khoản trước khi sử dụng.

## 3. Khởi tạo database từ máy vận hành

Cài Python 3.12, uv, libpq 16+ và root CA hệ thống; `uv sync --frozen`. Chạy các lệnh dưới đây trên Linux hoặc WSL, trong bản sao repo trên filesystem Linux của WSL. Đặt biến cho phiên hiện tại bằng giá trị thật, không ghi vào file theo dõi bởi Git. Chạy các lệnh có secret ở nơi riêng tư, không chụp màn hình hay đưa lịch sử lệnh lên mạng. Không dùng PowerShell Windows để tạo file mật khẩu seed: `chmod(0600)` của lệnh seed không bảo đảm ACL riêng tư trên Windows.

```bash
export DJANGO_SETTINGS_MODULE='config.settings.vercel'
export DJANGO_SECRET_KEY='<secret của môi trường demo>'
export DJANGO_ALLOWED_HOSTS='<hostname Vercel>'
export DJANGO_CSRF_TRUSTED_ORIGINS='https://<hostname Vercel>'
export POSTGRES_HOST='<hostname direct của Neon>'
export POSTGRES_DB='<database>'
export POSTGRES_USER='<user>'
export POSTGRES_PASSWORD='<password>'
export POSTGRES_PORT='5432'
uv run python manage.py check --deploy
uv run python manage.py migrate --noinput
uv run python manage.py seed_demo
```

`seed_demo` chỉ chạy trên database rỗng; mật khẩu riêng từng tài khoản được ghi vào `var/demo_credentials.txt` trên máy chạy lệnh. Bảo vệ file theo quyền hệ điều hành và xóa an toàn sau khi cấp thông tin; không chạy seed trên function. Sau đó deploy, kiểm tra login, CSRF, assets, phân quyền và `check --deploy`. Kiểm tra header IP thực tế và django-axes trước khi dựa vào chống brute force. Không dùng secret trong ví dụ làm mật khẩu thật.

## 4. Nhắc hạn hàng ngày

Workflow `.github/workflows/demo-reminders.yml` chạy lúc 07:17 giờ Việt Nam bằng hostname direct; không có endpoint HTTP mới. Trong GitHub tạo Environment `demo-reminders`, thêm secrets `DJANGO_SECRET_KEY`, `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` tương ứng với database demo. Cấu hình Environment không có yêu cầu approval cho job theo lịch. Workflow chỉ chạy theo lịch khi có trên nhánh mặc định; sau khi hợp nhất, có thể vào Actions > Demo reminders > Run workflow để chạy thử. Thao tác chạy lại được xử lý chống trùng bởi command.

GitHub Actions có thể chạy trễ/bỏ lượt, có hạn mức và scheduled workflow có thể bị tắt khi repo không hoạt động. Theo dõi kết quả Actions; khi thất bại, chạy lại thủ công sau khi khắc phục. Không chạy scheduler Compose cho cùng database. Lệnh tự bỏ qua trước 07:00 giờ Việt Nam; không dùng `--force` trừ khi chủ động chấp nhận chạy sớm.

## 5. Backup và kiểm tra

Trước mỗi migration, backup Neon bằng `pg_dump -Fc` qua kết nối direct TLS có xác minh; mã hóa và lưu ngoài repo. Restore vào database riêng bằng `pg_restore`, kiểm tra dữ liệu giả lập và trigger audit; không restore đè database đang phục vụ. Script Compose hiện tại không tự backup Neon.

Chạy suite trên PostgreSQL thật, gồm `uv run pytest -q -m "not e2e"` và test đồng thời; không dùng database demo chia sẻ vì test tạo/xóa database. Neon và Vercel thực tế còn cần được kiểm thử riêng, gồm TLS, collectstatic, proxy/IP, login, phân quyền, nộp đồng thời, nhắc và restore. Cấu hình này chưa phải minh chứng cho các kiểm thử đó.
