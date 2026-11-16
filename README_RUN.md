# README_RUN — Vận hành CAND PocketOps (demo, dữ liệu giả lập)

> Bản demo chỉ dùng dữ liệu giả lập. Không nhập dữ liệu thật, nội dung hồ sơ, thông tin công dân/điều tra.

Phương án Vercel Hobby + Neon Free và các điều kiện trước khi phát hành: [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md).

## 1. Chạy demo bằng Docker Compose (HTTPS nội bộ, chỉ 127.0.0.1)

```bash
cp .env.example .env          # rồi điền DJANGO_SECRET_KEY, POSTGRES_PASSWORD (sinh ngẫu nhiên)
chmod 600 .env
docker compose up -d --build  # db + web (gunicorn, migrate tự động) + scheduler (nhắc hạn mỗi giờ) + proxy (Caddy TLS internal)
docker compose exec web python manage.py seed_demo      # chỉ chạy trên DB rỗng
docker compose exec web cat var/demo_credentials.txt    # mật khẩu ngẫu nhiên từng tài khoản (file 0600)
```

Mở `https://localhost:8443` (chứng chỉ nội bộ của Caddy → trình duyệt cảnh báo, chấp nhận cho máy local).
Nếu đặt `DEMO_SEED_PASSWORD` trong `.env`, mọi tài khoản demo dùng mật khẩu đó (do người vận hành chọn, không có mặc định).

Tài khoản giả lập (đơn vị A): `lanhdao.a`, `truongphong.th`, `truongphong.db`, `canbo.th1`, `canbo.th2`, `canbo.db1`,
`canbo.db2`, `admin.a` (quản trị kỹ thuật). Đơn vị B: `lanhdao.b`, `truongphong.nb`, `truongphong.hc`, `canbo.nb1`,
`canbo.nb2`, `canbo.hc1`, `admin.b`.

Truy cập qua mạng (ngoài máy local): đặt sau reverse proxy HTTPS có chứng chỉ thật, cập nhật `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_HSTS_SECONDS`; giữ `DEBUG=False` (settings `config.settings.demo`). Không tự deploy public.

## 2. Phát triển local

```bash
uv sync                                     # Python 3.12, Django 5.2 LTS
npm ci && npm run build:css && npm run vendor:htmx   # Tailwind + HTMX build local, không CDN
docker run -d --name pocketops-pg -e POSTGRES_USER=pocketops -e POSTGRES_PASSWORD=devpass \
  -e POSTGRES_DB=pocketops -p 127.0.0.1:5432:5432 postgres:16-alpine
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver          # http://localhost:8000 (config.settings.dev)
```

## 3. Kiểm thử

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q -m "not e2e"              # cần PostgreSQL thật; gồm test race 2 connection (marker concurrency)
uv run pytest -q -m concurrency            # chỉ test đồng thời
E2E_BASE_URL=https://localhost:8443 E2E_USER=canbo.th1 E2E_PASSWORD=... uv run pytest -q -m e2e  # A28 browser
uv run pip-audit
DJANGO_SETTINGS_MODULE=config.settings.demo DJANGO_SECRET_KEY=... POSTGRES_PASSWORD=... \
  uv run python manage.py check --deploy
```

Không dùng SQLite cho test: settings test luôn trỏ PostgreSQL.

## 4. Nhắc hạn

`python manage.py send_due_reminders [--force]` — idempotent (dedupe recipient/record/type/ngày), bỏ qua trước 07:00 giờ VN
trừ khi `--force`. Container `scheduler` chạy lệnh này mỗi giờ. Không gửi email/SMS/push.

## 5. Migration

`docker compose exec web python manage.py migrate` (web tự chạy khi khởi động). Kiểm tra thiếu migration:
`uv run python manage.py makemigrations --check --dry-run`.

## 6. Backup / Restore

```bash
scripts/backup.sh [out_dir]                # pg_dump -Fc → backups/pocketops-<UTC>.dump (0600)
scripts/restore.sh <dump> [target_db]      # mặc định restore vào DB riêng `pocketops_restore`
scripts/restore_drill.sh [out_dir]         # A27: backup → restore → so sánh số bản ghi + kiểm trigger append-only
```

Thay DB đang chạy: `docker compose stop web scheduler` → `scripts/restore.sh <dump> pocketops` → `docker compose start web scheduler`.

## 7. Reset demo

```bash
docker compose down -v   # XÓA toàn bộ dữ liệu demo (volume pgdata/appvar)
```
