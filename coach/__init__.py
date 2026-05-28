"""Coach analysis engine — pure functions, no I/O."""

from statistics import mean
from typing import Any

from .thresholds import *  # noqa: F403

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return mean(clean) if clean else None


def _trend(recent: float | None, previous: float | None,
           threshold_pct: float | None = None) -> str:
    """Return Rising / Stable / Falling based on % change between two averages."""
    from .thresholds import TREND_PCT
    if threshold_pct is None:
        threshold_pct = TREND_PCT
    if recent is None or previous is None or previous == 0:
        return "Stable"
    change = ((recent - previous) / abs(previous)) * 100
    if change > threshold_pct:
        return "Rising"
    if change < -threshold_pct:
        return "Falling"
    return "Stable"


def _confidence(n_values: int) -> str:
    if n_values >= 7:
        return "high"
    if n_values >= 3:
        return "medium"
    return "low"


def _trend_detail(recent: float | None, previous: float | None,
                  threshold_pct: float | None = None) -> dict:
    """Return {direction, delta_pct, confidence} for a pair of averages."""
    from .thresholds import TREND_PCT
    if threshold_pct is None:
        threshold_pct = TREND_PCT
    if recent is None or previous is None or previous == 0:
        return {"direction": "Stable", "delta_pct": None, "confidence": "low"}
    delta = ((recent - previous) / abs(previous)) * 100
    if delta > threshold_pct:
        direction = "Rising"
    elif delta < -threshold_pct:
        direction = "Falling"
    else:
        direction = "Stable"
    return {"direction": direction, "delta_pct": round(delta, 1),
            "confidence": "medium"}


def _format_pace(seconds_per_km: float | None) -> str | None:
    """Convert pace from sec/km to m:ss/km string."""
    if not seconds_per_km or seconds_per_km <= 0:
        return None
    m = int(seconds_per_km // 60)
    s = int(seconds_per_km % 60)
    return f"{m}:{s:02d}/km"


# ---------------------------------------------------------------------------
# Re-exports — domain functions
# ---------------------------------------------------------------------------

from .readiness import assess_readiness, determine_overall_status  # noqa: E402
from .fatigue import assess_fatigue  # noqa: E402
from .recovery import analyze_hrv_trend, analyze_sleep_trend  # noqa: E402
from .training import (  # noqa: E402
    compute_training_status,
    compute_weekly_comparison,
    compute_trends,
    summarize_recent_training,
    build_data_freshness,
    analyze_plan_projection,
)
from .safety import (  # noqa: E402
    build_training_guardrails,
    generate_alerts,
    build_evidence_summary,
)
from .recommendation import generate_recommendation  # noqa: E402
