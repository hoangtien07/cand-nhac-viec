"""Settings for the synthetic-data Vercel + Neon demo."""

from .base import env
from .demo import *  # noqa: F403

DATABASES["default"].update(  # noqa: F405
    HOST=env("POSTGRES_HOST", required=True),
    NAME=env("POSTGRES_DB", required=True),
    USER=env("POSTGRES_USER", required=True),
    CONN_MAX_AGE=0,
    DISABLE_SERVER_SIDE_CURSORS=True,
    OPTIONS={"connect_timeout": 15, "sslmode": "verify-full", "sslrootcert": "system"},
)

# Vercel serves collected assets via its CDN. The vendored Chart.js references
# an unshipped sourcemap, so manifest URL rewriting cannot process it.
STORAGES["staticfiles"] = {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}  # noqa: F405
