"""Deterministic KPI score engine (PLAN §4 formulas). All Decimal; no client input is trusted.

base_score = max_points × Σ[(w_i / 100) × (a_i / 100)]
L          = matching LATE_DAYS band deduction_percent
R          = matching REMINDER_COUNT band deduction_percent
final      = strategy(base_score, L, R), clamped to [0, max_points], ROUND_HALF_UP 2dp
"""

from decimal import ROUND_HALF_UP, Decimal

from .models import CombinationStrategy, PenaltyBandKind

D = Decimal
CENT = D("0.01")
PCT = D("100")


def matching_band(version, kind, value):
    """Return the band covering `value`, or None when no band matches."""
    for band in version.penalty_bands.filter(kind=kind).order_by("min_value"):
        if band.min_value <= value and (band.max_value is None or value <= band.max_value):
            return band
    return None


def band_deduction(version, kind, value):
    band = matching_band(version, kind, value)
    return band.deduction_percent if band else D("0")


def apply_strategy(base_score, late_pct, reminder_pct, strategy, max_points):
    if strategy == CombinationStrategy.MAX_DEDUCTION:
        final = base_score * (1 - max(late_pct, reminder_pct) / PCT)
    elif strategy == CombinationStrategy.CAPPED_ADDITIVE:
        final = base_score * (1 - min(PCT, late_pct + reminder_pct) / PCT)
    elif strategy == CombinationStrategy.MULTIPLICATIVE:
        final = base_score * (1 - late_pct / PCT) * (1 - reminder_pct / PCT)
    else:  # pragma: no cover - choices are enforced at the schema level
        raise ValueError(f"Unknown strategy {strategy!r}")
    return min(max(D("0"), final), max_points).quantize(CENT, rounding=ROUND_HALF_UP)


def compute_score(version, achievements, late_days, reminder_count, strategy=None):
    """achievements: {criterion_id: Decimal(0..100)}. Returns a plain dict (no DB writes)."""
    strategy = strategy or version.combination_strategy
    base = D("0")
    for crit in version.criteria.all():
        a = achievements.get(str(crit.pk), achievements.get(crit.pk))
        if a is None:
            continue
        base += D(crit.weight_percent) / PCT * D(str(a)) / PCT
    base_score = (version.max_points * base)
    late_pct = band_deduction(version, PenaltyBandKind.LATE_DAYS, late_days)
    rem_pct = band_deduction(version, PenaltyBandKind.REMINDER_COUNT, reminder_count)
    final = apply_strategy(base_score, late_pct, rem_pct, strategy, version.max_points)
    return {
        "base_score": base_score.quantize(CENT, rounding=ROUND_HALF_UP),
        "late_days": late_days,
        "reminder_count": reminder_count,
        "late_deduction_percent": late_pct,
        "reminder_deduction_percent": rem_pct,
        "strategy": strategy,
        "final_score": final,
    }
