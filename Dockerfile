# syntax=docker/dockerfile:1
FROM node:22-alpine AS assets
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY assets assets
COPY templates templates
COPY apps apps
RUN mkdir -p static/css static/vendor \
 && npx tailwindcss -i assets/app.css -o static/css/app.css --minify \
 && cp node_modules/htmx.org/dist/htmx.min.js static/vendor/htmx.min.js

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=config.settings.demo
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
COPY --from=assets /src/static/css static/css
COPY --from=assets /src/static/vendor static/vendor
RUN DJANGO_SECRET_KEY=build-only POSTGRES_PASSWORD=build-only python manage.py collectstatic --noinput -v0 \
 && useradd --system --uid 10001 app && mkdir -p /app/var && chown app /app/var
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
