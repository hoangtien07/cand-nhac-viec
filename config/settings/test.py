import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-secret")
os.environ.setdefault("POSTGRES_PASSWORD", "devpass")

from .base import *  # noqa: E402,F403

DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
AXES_ENABLED = True
