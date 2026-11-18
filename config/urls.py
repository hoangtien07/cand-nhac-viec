from django.urls import include, path

from apps.accounts.views import healthz
from apps.records.views import dashboard

# Django admin is intentionally NOT mounted: business records must never be browsable by technical
# admins (AGENTS.md). Technical administration lives at /quan-tri/.
urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("", include("apps.accounts.urls")),
    path("healthz/", healthz, name="healthz"),
    path("ho-so/", include("apps.records.urls")),
    path("nhom-ho-so/", include("apps.organization.folder_urls")),
    path("thong-bao/", include("apps.notifications.urls")),
    path("bao-cao/", include("apps.reports.urls")),
    path("kpi/", include("apps.kpi.urls")),
    path("quan-tri/", include("apps.kpi.admin_urls")),
    path("quan-tri/", include("apps.accounts.admin_urls")),
]

handler403 = "apps.accounts.errors.forbidden"
handler404 = "apps.accounts.errors.not_found"
