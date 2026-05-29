"""Coach analysis engine — pure functions, no I/O.

Modules that provide unique value beyond what the Coros app already shows:
  - efficiency       Pace-vs-HR crossover → is training working?
  - safety           Multi-signal alerts + thresholds → injury risk detection
"""

from statistics import mean
from typing import Any

TREND_PCT = 5.0  # min % change to call a trend Rising or Falling

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
# Public API
# ---------------------------------------------------------------------------

from .safety import (            # noqa: E402
    build_training_guardrails,
    generate_alerts,
    build_evidence_summary,
)
from .efficiency import analyse_efficiency, analyse_pace_at_hr  # noqa: E402
