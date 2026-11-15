from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("da-doc-tat-ca/", views.mark_all_read, name="mark_all_read"),
    path("badge/", views.badge, name="badge"),
    path("<uuid:pk>/da-doc/", views.mark_read, name="mark_read"),
]
