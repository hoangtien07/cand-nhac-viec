"""KPI config screens (PLAN §7.2). Flag off -> 404; missing capability -> 403; cross-unit id -> 404."""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import policies, services
from .capabilities import KpiCapability
from .forms import (
    CriterionFormSet,
    PenaltyBandFormSet,
    PreviewForm,
    PublishForm,
    VersionCreateForm,
    VersionMetaForm,
)
from .models import CombinationStrategy, KpiPolicyVersion, PolicyVersionStatus
from .scoring import compute_score


def kpi_view(fn):
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        if not policies.kpi_enabled():
            raise Http404
        return fn(request, *args, **kwargs)

    return wrapper


def _err_messages(exc):
    return list(getattr(exc, "messages", None) or [str(a) for a in exc.args] or [str(exc)])


def _version_or_404(user, version_id):
    try:
        return services._version_in_unit(user, version_id)
    except KpiPolicyVersion.DoesNotExist:
        raise Http404 from None


def _criteria_initial(version):
    return [
        {
            "code": c.code, "title": c.title, "weight_percent": c.weight_percent,
            "position": c.position, "description_short": c.description_short,
            "required": c.required,
        }
        for c in version.criteria.all()
    ]


def _bands_initial(version):
    return [
        {
            "kind": b.kind, "min_value": b.min_value, "max_value": b.max_value,
            "deduction_percent": b.deduction_percent,
        }
        for b in version.penalty_bands.all()
    ]


def _version_ctx(user, version, **extra):
    return {
        "version": version,
        "family": version.family,
        "is_draft": version.status == PolicyVersionStatus.DRAFT,
        "validation_errors": services.validate_version(version),
        "can_edit": policies.has_capability(user, KpiCapability.CONFIG_EDIT),
        "can_publish": policies.has_capability(user, KpiCapability.CONFIG_PUBLISH),
        **extra,
    }


@kpi_view
def config_list(request):
    policies.require(policies.can_view_kpi_config(request.user))
    versions = services.visible_versions(request.user)
    return render(
        request, "kpi/config_list.html",
        {"versions": versions, "can_edit": policies.has_capability(request.user, KpiCapability.CONFIG_EDIT)},
    )


@kpi_view
def config_create(request):
    policies.require(policies.can_configure_kpi(request.user))
    form = VersionCreateForm(request.POST or None)
    form.fields["clone_from"].choices = [("", "— Tạo mới —")] + [
        (str(v.pk), f"{v.family.name} v{v.version}")
        for v in services.visible_versions(request.user)
    ]
    if request.method == "POST" and form.is_valid():
        try:
            version = services.create_draft(
                request.user,
                task_kind=form.cleaned_data["task_kind"],
                name=form.cleaned_data["name"],
                max_points=form.cleaned_data["max_points"],
                combination_strategy=form.cleaned_data["combination_strategy"],
                clone_from_id=form.cleaned_data["clone_from"] or None,
            )
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f"Đã tạo bản nháp v{version.version}.")
            return redirect("kpi:config_detail", version.pk)
    return render(request, "kpi/config_create.html", {"form": form})


@kpi_view
def config_detail(request, version_id):
    version = _version_or_404(request.user, version_id)
    user = request.user
    policies.require(policies.can_view_kpi_config(user))
    meta_form = VersionMetaForm(
        initial={"max_points": version.max_points, "combination_strategy": version.combination_strategy}
    )
    criteria_fs = CriterionFormSet(initial=_criteria_initial(version), prefix="crit")
    bands_fs = PenaltyBandFormSet(initial=_bands_initial(version), prefix="band")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "meta":
            meta_form = VersionMetaForm(request.POST)
            if meta_form.is_valid():
                try:
                    services.update_draft(user, version_id, **meta_form.cleaned_data)
                    messages.success(request, "Đã lưu thông tin phiên bản.")
                    return redirect("kpi:config_detail", version_id)
                except (ValidationError, PermissionDenied) as e:
                    meta_form.add_error(None, e)
        elif action == "criteria":
            criteria_fs = CriterionFormSet(request.POST, prefix="crit")
            if criteria_fs.is_valid():
                rows = [
                    {k: f.cleaned_data[k] for k in ("code", "title", "weight_percent", "position",
                                                   "description_short", "required")}
                    for f in criteria_fs.forms
                    if f.cleaned_data and not f.cleaned_data.get("DELETE")
                ]
                try:
                    services.replace_criteria(user, version_id, rows)
                    messages.success(request, f"Đã lưu {len(rows)} tiêu chí.")
                    return redirect("kpi:config_detail", version_id)
                except (ValidationError, PermissionDenied) as e:
                    criteria_fs._non_form_errors = criteria_fs.error_class(
                        criteria_fs, error_class="nonform"
                    )
                    criteria_fs._non_form_errors.extend(_err_messages(e))
        elif action == "bands":
            bands_fs = PenaltyBandFormSet(request.POST, prefix="band")
            if bands_fs.is_valid():
                rows = [
                    {k: f.cleaned_data[k] for k in ("kind", "min_value", "max_value", "deduction_percent")}
                    for f in bands_fs.forms
                    if f.cleaned_data and not f.cleaned_data.get("DELETE")
                ]
                try:
                    services.replace_penalty_bands(user, version_id, rows)
                    messages.success(request, f"Đã lưu {len(rows)} dải trừ.")
                    return redirect("kpi:config_detail", version_id)
                except (ValidationError, PermissionDenied) as e:
                    bands_fs._non_form_errors = bands_fs.error_class(bands_fs, error_class="nonform")
                    bands_fs._non_form_errors.extend(_err_messages(e))
    version = _version_or_404(request.user, version_id)  # reload after writes
    ctx = _version_ctx(user, version, meta_form=meta_form, criteria_fs=criteria_fs,
                       bands_fs=bands_fs, preview_form=PreviewForm(), publish_form=PublishForm())
    return render(request, "kpi/config_detail.html", ctx)


@kpi_view
@require_POST
def config_preview(request, version_id):
    version = _version_or_404(request.user, version_id)
    policies.require(
        policies.has_capability(request.user, KpiCapability.CONFIG_EDIT)
        or policies.has_capability(request.user, KpiCapability.CONFIG_PUBLISH)
    )
    form = PreviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Dữ liệu mô phỏng không hợp lệ.")
        return redirect("kpi:config_detail", version_id)
    d = form.cleaned_data
    achievements = {str(c.pk): d["achievement"] for c in version.criteria.all()}
    strategies = [d["strategy"]] if d["strategy"] else [s for s, _ in CombinationStrategy.choices]
    results = [
        compute_score(version, achievements, d["late_days"], d["reminder_count"], strategy=s)
        for s in strategies
    ]
    meta_form = VersionMetaForm(
        initial={"max_points": version.max_points, "combination_strategy": version.combination_strategy}
    )
    ctx = _version_ctx(
        request.user, version,
        meta_form=meta_form,
        criteria_fs=CriterionFormSet(initial=_criteria_initial(version), prefix="crit"),
        bands_fs=PenaltyBandFormSet(initial=_bands_initial(version), prefix="band"),
        preview_form=form, publish_form=PublishForm(), preview_results=results,
    )
    return render(request, "kpi/config_detail.html", ctx)


@kpi_view
@require_POST
def config_publish(request, version_id):
    _version_or_404(request.user, version_id)
    policies.require(policies.can_publish_kpi(request.user))
    form = PublishForm(request.POST)
    if form.is_valid():
        try:
            services.publish_version(request.user, version_id, form.cleaned_data["reason"])
            messages.success(request, "Đã kích hoạt phiên bản cấu hình KPI.")
            return redirect("kpi:config_detail", version_id)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
    else:
        messages.error(request, "Cần nhập lý do xác nhận.")
    return redirect("kpi:config_detail", version_id)


# --- WP5: reminders + evaluation ---

from . import evaluation_services as esvc  # noqa: E402
from . import reminder_services as rsvc  # noqa: E402
from .forms import EvaluationMarksForm, ReminderForm  # noqa: E402
from .models import KpiEvaluation  # noqa: E402


@kpi_view
@require_POST
def reminder_issue(request, record_id):
    form = ReminderForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Dữ liệu nhắc nhở không hợp lệ.")
        return redirect("records:detail", record_id)
    try:
        rsvc.issue_reminder(
            request.user, record_id=record_id,
            subject_user_id=form.cleaned_data["subject_user"],
            reason=form.cleaned_data["reason"],
            idempotency_key=form.cleaned_data["idempotency_key"],
        )
        messages.success(request, "Đã ghi nhận nhắc nhở KPI.")
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
    return redirect("records:detail", record_id)


@kpi_view
@require_POST
def reminder_revoke(request, event_id):
    reason = (request.POST.get("reason") or "").strip()
    try:
        rsvc.revoke_reminder(request.user, event_id=event_id, reason=reason)
        messages.success(request, "Đã hủy nhắc nhở KPI.")
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
    return redirect(request.POST.get("next") or "/")


@kpi_view
@require_POST
def evaluation_start(request, record_id, subject_user_id):
    try:
        evaluation, _created = esvc.get_or_create_evaluation(
            request.user, record_id=record_id, subject_user_id=subject_user_id
        )
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
        return redirect("records:detail", record_id)
    return redirect("kpi:evaluation_detail", evaluation.pk)


@kpi_view
def evaluation_detail(request, evaluation_id):
    try:
        evaluation = esvc._evaluation_in_unit(request.user, evaluation_id)
    except KpiEvaluation.DoesNotExist:
        raise Http404 from None
    user = request.user
    scoped = policies.user_departments_scope(user, KpiCapability.EVALUATE)
    can_mark = policies.can_evaluate(user, evaluation.record.owner_department_id)
    can_close = policies.can_finalize(user, evaluation.record.owner_department_id)
    can_fix = policies.can_correct_score(user, evaluation.record.owner_department_id)
    is_owner = user.pk == evaluation.subject_user_id
    if not (can_mark or can_close or is_owner):
        raise PermissionDenied("Bạn không có quyền xem đánh giá này.")
    if is_owner and evaluation.status != "FINALIZED":
        raise Http404  # officer chỉ xem điểm đã chốt của mình
    form = EvaluationMarksForm(evaluation=evaluation, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            esvc.save_marks(
                user, evaluation_id, form.marks(),
                expected_row_version=request.POST.get("row_version"),
            )
            messages.success(request, "Đã lưu đánh giá.")
            return redirect("kpi:evaluation_detail", evaluation_id)
        except ValidationError as e:
            for m in e.messages:
                form.add_error(None, m)
    marks = {str(m.criterion_id): m for m in evaluation.marks.all()}
    preview = esvc.score_preview(evaluation) if can_mark or can_close else None
    snapshot = esvc.effective_snapshot(evaluation)
    criteria = list(evaluation.policy_version.criteria.all())
    mark_rows = [(c, form[f"mark-{c.pk}"], marks.get(str(c.pk))) for c in criteria]
    return render(request, "kpi/evaluation_detail.html", {
        "evaluation": evaluation, "form": form, "marks": marks,
        "criteria": criteria, "mark_rows": mark_rows,
        "can_mark": can_mark and evaluation.status == "DRAFT",
        "can_close": can_close and evaluation.status == "DRAFT",
        "can_fix": can_fix and evaluation.status == "FINALIZED",
        "preview": preview, "snapshot": snapshot,
        "scoped": scoped,
    })


@kpi_view
@require_POST
def evaluation_finalize(request, evaluation_id):
    try:
        esvc._evaluation_in_unit(request.user, evaluation_id)
    except KpiEvaluation.DoesNotExist:
        raise Http404 from None
    try:
        esvc.finalize_evaluation(
            request.user, evaluation_id,
            expected_row_version=request.POST.get("row_version"),
        )
        messages.success(request, "Đã chốt điểm KPI.")
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
    return redirect("kpi:evaluation_detail", evaluation_id)


@kpi_view
@require_POST
def evaluation_correct(request, evaluation_id):
    try:
        esvc._evaluation_in_unit(request.user, evaluation_id)
    except KpiEvaluation.DoesNotExist:
        raise Http404 from None
    reason = (request.POST.get("reason") or "").strip()
    marks = {}
    for key, value in request.POST.items():
        if key.startswith("mark-"):
            marks[key[5:]] = value
    try:
        esvc.correct_score(
            request.user, evaluation_id, reason=reason,
            marks=marks or None, expected_row_version=request.POST.get("row_version"),
        )
        messages.success(request, "Đã tạo bản điều chỉnh điểm.")
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
    return redirect("kpi:evaluation_detail", evaluation_id)

