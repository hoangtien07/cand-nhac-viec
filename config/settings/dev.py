import os

os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-not-secret-change-me")
os.environ.setdefault("POSTGRES_PASSWORD", "devpass")

from .base import *  # noqa: E402,F403
from .base import env_list  # noqa: E402

DEBUG = True
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
