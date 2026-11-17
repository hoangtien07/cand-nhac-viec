"""KPI capability codes (PLAN §5.2). Grants are per user+unit — never derived from roles."""


class KpiCapability:
    CONFIG_VIEW = "KPI_CONFIG_VIEW"
    CONFIG_EDIT = "KPI_CONFIG_EDIT"
    CONFIG_PUBLISH = "KPI_CONFIG_PUBLISH"
    REMINDER_ISSUE = "KPI_REMINDER_ISSUE"
    EVALUATE = "KPI_EVALUATE"
    SCORE_FINALIZE = "KPI_SCORE_FINALIZE"
    SCORE_CORRECT = "KPI_SCORE_CORRECT"
    VIEW_UNIT = "KPI_VIEW_UNIT"
    GRANT_MANAGE = "KPI_GRANT_MANAGE"


BUSINESS_CAPABILITIES = (
    KpiCapability.CONFIG_VIEW,
    KpiCapability.CONFIG_EDIT,
    KpiCapability.CONFIG_PUBLISH,
    KpiCapability.REMINDER_ISSUE,
    KpiCapability.EVALUATE,
    KpiCapability.SCORE_FINALIZE,
    KpiCapability.SCORE_CORRECT,
    KpiCapability.VIEW_UNIT,
)

CAPABILITY_CHOICES = tuple(
    (cap, label)
    for cap, label in [
        (KpiCapability.CONFIG_VIEW, "Xem cấu hình KPI"),
        (KpiCapability.CONFIG_EDIT, "Soạn cấu hình KPI"),
        (KpiCapability.CONFIG_PUBLISH, "Kích hoạt cấu hình KPI"),
        (KpiCapability.REMINDER_ISSUE, "Ghi nhận nhắc nhở KPI"),
        (KpiCapability.EVALUATE, "Đánh giá tiêu chí KPI"),
        (KpiCapability.SCORE_FINALIZE, "Chốt điểm KPI"),
        (KpiCapability.SCORE_CORRECT, "Điều chỉnh điểm sau chốt"),
        (KpiCapability.VIEW_UNIT, "Xem điểm toàn đơn vị"),
        (KpiCapability.GRANT_MANAGE, "Cấp/thu hồi quyền KPI"),
    ]
)
