from django.urls import path

from . import grant_views

app_name = "kpi_admin"

# Mounted at /quan-tri/ in config.urls -> /quan-tri/kpi-quyen/ (PLAN §7.2).
urlpatterns = [
    path("kpi-quyen/", grant_views.grant_list, name="grant_list"),
    path("kpi-quyen/<uuid:grant_id>/thu-hoi/", grant_views.grant_revoke, name="grant_revoke"),
]
