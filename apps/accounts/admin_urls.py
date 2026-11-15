from django.urls import path

from . import admin_views

app_name = "adminpanel"
urlpatterns = [
    path("", admin_views.home, name="home"),
    path("tai-khoan/tao/", admin_views.user_create, name="user_create"),
    path("tai-khoan/<int:pk>/", admin_views.user_edit, name="user_edit"),
    path("phong/tao/", admin_views.department_form, name="department_create"),
    path("phong/<uuid:pk>/", admin_views.department_form, name="department_edit"),
]
