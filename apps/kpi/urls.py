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

urlpatterns += [
    path("nhiem-vu/<uuid:record_id>/nhac-nho/", views.reminder_issue, name="reminder_issue"),
    path("nhac-nho/<uuid:event_id>/huy/", views.reminder_revoke, name="reminder_revoke"),
    path(
        "nhiem-vu/<uuid:record_id>/danh-gia/<uuid:subject_user_id>/",
        views.evaluation_start, name="evaluation_start",
    ),
    path("danh-gia/<uuid:evaluation_id>/", views.evaluation_detail, name="evaluation_detail"),
    path("danh-gia/<uuid:evaluation_id>/chot/", views.evaluation_finalize, name="evaluation_finalize"),
    path("danh-gia/<uuid:evaluation_id>/dieu-chinh/", views.evaluation_correct, name="evaluation_correct"),
]

urlpatterns += [
    path("ca-nhan/", views.my_scores, name="my_scores"),
    path("bang-diem/", views.score_board, name="score_board"),
    path("danh-gia/", views.evaluation_list, name="evaluation_list"),
    path("nhac-nho/", views.reminder_list, name="reminder_list"),
]
