from django.urls import path

from . import views

app_name = "kpi"

urlpatterns = [
    path("cau-hinh/", views.config_list, name="config_list"),
    path("cau-hinh/tao/", views.config_create, name="config_create"),
    path("cau-hinh/<uuid:version_id>/", views.config_detail, name="config_detail"),
    path("cau-hinh/<uuid:version_id>/preview/", views.config_preview, name="config_preview"),
    path("cau-hinh/<uuid:version_id>/kich-hoat/", views.config_publish, name="config_publish"),
]
