from django.urls import path

from . import views

app_name = "records"

urlpatterns = [
    path("", views.record_list, name="list"),
    path("tao/", views.record_create, name="create"),
    path("nam-lam-viec/", views.set_work_year, name="set_work_year"),
    path("<uuid:pk>/", views.record_detail, name="detail"),
    path("<uuid:pk>/nop/", views.submit_result, name="submit"),
    path("<uuid:pk>/nguoi-xu-ly/", views.update_assignment, name="assignment"),
    path("<uuid:pk>/theo-doi/", views.update_watchers, name="watchers"),
    path("<uuid:pk>/han/", views.update_deadline, name="deadline"),
]
