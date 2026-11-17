from django.urls import path

from apps.organization import folder_views

from . import views

app_name = "records"

urlpatterns = [
    path("", views.record_list, name="list"),
    path("tao/", views.record_create, name="create"),
    path("nam-lam-viec/", views.set_work_year, name="set_work_year"),
    path("nop-nhanh/", views.quick_submit, name="quick_submit"),
    path("nop-nhanh/tim/", views.quick_submit_search, name="quick_submit_search"),
    path("nop-nhanh/chon/", views.quick_submit_pick, name="quick_submit_pick"),
    path("<uuid:pk>/", views.record_detail, name="detail"),
    path("<uuid:pk>/sua/", views.record_edit, name="edit"),
    path("<uuid:pk>/luu-tru/", views.archive_record, name="archive"),
    path("<uuid:pk>/khoi-phuc/", views.restore_record, name="restore"),
    path("<uuid:pk>/nop/", views.submit_result, name="submit"),
    path("<uuid:pk>/ket-qua/<uuid:result_id>/dinh-chinh/", views.correct_result, name="correct"),
    path("<uuid:pk>/ket-qua/<uuid:result_id>/huy/", views.revoke_result, name="revoke"),
    path("<uuid:pk>/nguoi-xu-ly/", views.update_assignment, name="assignment"),
    # STT2: watcher management UI/endpoint retired (D13: no new watchers; legacy rows keep
    # their read access until a migration decision is approved).
    path("<uuid:pk>/han/", views.update_deadline, name="deadline"),
    path("<uuid:pk>/chia-se/", folder_views.share_record, name="share"),
    path("<uuid:pk>/chia-se/<int:share_id>/thu-hoi/", folder_views.unshare_record, name="unshare"),
    path("<uuid:pk>/nhom/", folder_views.set_folder, name="set_folder"),
]
