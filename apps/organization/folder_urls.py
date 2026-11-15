from django.urls import path

from . import folder_views as views

app_name = "folders"

urlpatterns = [
    path("", views.index, name="index"),
    path("tao/", views.create, name="create"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/doi-ten/", views.rename, name="rename"),
    path("<uuid:pk>/thanh-vien/", views.grant, name="grant"),
    path("<uuid:pk>/thanh-vien/<int:grant_id>/thu-hoi/", views.revoke, name="revoke"),
]
