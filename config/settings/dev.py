import os

os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-not-secret-change-me")
os.environ.setdefault("POSTGRES_PASSWORD", "devpass")

from .base import *  # noqa: E402,F403

DEBUG = True
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
