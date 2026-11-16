import os
import subprocess
import sys


def test_vercel_settings_require_explicit_database_configuration():
    env = os.environ.copy()
    env.update(DJANGO_SECRET_KEY="test-secret", POSTGRES_PASSWORD="test-password")
    for name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER"):
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.vercel"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "POSTGRES_HOST" in result.stderr


def test_vercel_settings_enforce_tls_and_disable_persistent_connections():
    env = os.environ.copy()
    env.update(
        DJANGO_SECRET_KEY="test-secret",
        POSTGRES_PASSWORD="test-password",
        POSTGRES_HOST="example.neon.tech",
        POSTGRES_DB="demo",
        POSTGRES_USER="demo",
    )
    code = (
        "from config.settings.vercel import DATABASES; "
        "db = DATABASES['default']; "
        "assert db['HOST'] == 'example.neon.tech'; "
        "assert db['OPTIONS']['sslmode'] == 'verify-full'; "
        "assert db['OPTIONS']['sslrootcert'] == 'system'; "
        "assert db['CONN_MAX_AGE'] == 0"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_vercel_collectstatic_accepts_vendored_chart_without_sourcemap(tmp_path):
    env = os.environ.copy()
    env.update(
        DJANGO_SECRET_KEY="test-secret",
        POSTGRES_PASSWORD="test-password",
        POSTGRES_HOST="example.neon.tech",
        POSTGRES_DB="demo",
        POSTGRES_USER="demo",
    )
    code = (
        "import django; from django.conf import settings; "
        f"settings.STATIC_ROOT = {str(tmp_path)!r}; "
        "django.setup(); from django.core.management import call_command; "
        "call_command('collectstatic', interactive=False, verbosity=0)"
    )
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.vercel"
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "vendor" / "chart.umd.js").exists()
