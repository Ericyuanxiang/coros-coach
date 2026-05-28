"""Readiness assessment — "Can I train today?"."""

from typing import Any

from . import _safe_float, _avg
from .thresholds import (
    HRV_GOOD_THRESHOLD,
    HRV_FAIR_THRESHOLD,
    SLEEP_GOOD_MINUTES,
    SLEEP_FAIR_MINUTES,
    SLEEP_GOOD_QUALITY,
    SLEEP_FAIR_QUALITY,
    RHR_ELEVATED_BPM,
)


# ---------------------------------------------------------------------------
# Sub-scores
# ---------------------------------------------------------------------------

def _hrv_score(daily_records: list[dict]) -> tuple[int | None, str]:
    """Return (points, human_readable_reason). 0–2 pts."""
    hrvs = [(r.get("avg_sleep_hrv"), r.get("baseline")) for r in daily_records
            if r.get("avg_sleep_hrv") is not None]
    if len(hrvs) < 3:
        return 1, "Insufficient HRV data (< 3 days) → default Fair (1 pt)"

    latest_hrv, baseline = hrvs[0]
    if baseline is None:
        baseline = _avg([h for h, _ in hrvs])

    if latest_hrv is None or baseline is None or baseline <= 0:
        return 1, "Cannot compute HRV deviation → default Fair (1 pt)"

    deviation = ((latest_hrv - baseline) / baseline) * 100

    if deviation > -HRV_GOOD_THRESHOLD * 1.5:
        return 2, f"HRV {deviation:+.0f}% vs baseline → elevated, excellent recovery"
    if deviation > HRV_GOOD_THRESHOLD:
        return 1, f"HRV {deviation:+.0f}% vs baseline → normal"
    if deviation > HRV_FAIR_THRESHOLD:
        return 0, f"HRV {deviation:+.0f}% vs baseline → below normal, moderate fatigue"
    return 0, f"HRV {deviation:+.0f}% vs baseline → critically low, poor recovery"


def _sleep_score(sleep_records: list[dict]) -> tuple[int | None, str]:
    """Return (points, reason). 0–2 pts."""
    if not sleep_records or len(sleep_records) < 3:
        return 1, "Insufficient sleep data → default Fair (1 pt)"

    recent = sleep_records[:7]
    durations = [r.get("total_duration_minutes") for r in recent
                 if r.get("total_duration_minutes") is not None]
    qualities = [r.get("quality_score") for r in recent
                 if r.get("quality_score") is not None and r.get("quality_score", -1) >= 0]

    avg_dur = _avg(durations)
    avg_qual = _avg(qualities)

    if avg_dur is None:
        avg_dur = 0

    points = 0
    reasons = []

    if avg_dur >= SLEEP_GOOD_MINUTES:
        points += 1
        reasons.append(f"avg {avg_dur:.0f}min → good duration")
    elif avg_dur >= SLEEP_FAIR_MINUTES:
        reasons.append(f"avg {avg_dur:.0f}min → fair duration")
    else:
        reasons.append(f"avg {avg_dur:.0f}min → poor duration")

    if avg_qual is not None and avg_qual >= SLEEP_GOOD_QUALITY:
        points += 1
        reasons.append(f"quality {avg_qual:.0f}/100 → good quality")
    elif avg_qual is not None and avg_qual >= SLEEP_FAIR_QUALITY:
        reasons.append(f"quality {avg_qual:.0f}/100 → fair quality")
    elif avg_qual is not None:
        reasons.append(f"quality {avg_qual:.0f}/100 → poor quality")

    return points, "; ".join(reasons) if reasons else "Sleep data ambiguous"


def _rhr_score(daily_records: list[dict], rhr_baseline: int | None = None) -> tuple[int | None, str]:
    """Return (points, reason). 0–2 pts."""
    rhrs = [(r.get("rhr"), r.get("date")) for r in daily_records
            if r.get("rhr") is not None]
    if len(rhrs) < 3:
        return 1, "Insufficient RHR data → default Fair (1 pt)"

    latest_rhr = rhrs[0][0]
    week_avg = _avg([h for h, _ in rhrs[1:7]])
    if week_avg is None:
        week_avg = rhr_baseline or latest_rhr

    diff = latest_rhr - week_avg
    if diff <= 0:
        return 2, f"RHR {latest_rhr} bpm ≤ 7d avg → recovering well"
    if diff <= RHR_ELEVATED_BPM:
        return 1, f"RHR {latest_rhr} bpm slightly above 7d avg → mild stress"
    return 0, f"RHR {latest_rhr} bpm elevated by {diff:.0f} vs 7d avg → significant stress"


# ---------------------------------------------------------------------------
# Main readiness function
# ---------------------------------------------------------------------------

def assess_readiness(
    daily_records: list[dict],
    sleep_records: list[dict] | None = None,
    user_profile: dict | None = None,
    recovery_hours: int | None = None,
) -> dict:
    """Score readiness 0-10 from HRV (3pts), sleep (3pts), RHR (2pts), recovery (2pts).

    Returns dict with: score (Ready/Moderate/Recover/Rest), ratio, detail,
    contributing_factors.
    """
    sleep_records = sleep_records or []
    user_profile = user_profile or {}

    hrv_pts, hrv_reason = _hrv_score(daily_records)
    sleep_pts, sleep_reason = _sleep_score(sleep_records)
    rhr_pts, rhr_reason = _rhr_score(daily_records, user_profile.get("rhr"))

    # Recovery hours (from dashboard)
    recovery_pts = 2
    recovery_reason = ""
    if recovery_hours is not None:
        if recovery_hours <= 0:
            recovery_pts = 2
            recovery_reason = "Recovery complete (0h remaining)"
        elif recovery_hours <= 8:
            recovery_pts = 1
            recovery_reason = f"Recovery: {recovery_hours}h remaining → slight residual"
        elif recovery_hours <= 24:
            recovery_pts = 0
            recovery_reason = f"Recovery: {recovery_hours}h remaining → recommend easy day"
        else:
            recovery_pts = 0
            recovery_reason = f"Recovery: {recovery_hours}h remaining → rest recommended"

    total = (hrv_pts or 0) + (sleep_pts or 0) + (rhr_pts or 0) + recovery_pts
    max_possible = 10
    ratio = total / max_possible

    if ratio >= 0.80:
        score = "Ready"
    elif ratio >= 0.60:
        score = "Moderate"
    elif ratio >= 0.40:
        score = "Recover"
    else:
        score = "Rest"

    factors = []
    if hrv_reason:
        factors.append(f"HRV: {hrv_reason}")
    if sleep_reason:
        factors.append(f"Sleep: {sleep_reason}")
    if rhr_reason:
        factors.append(f"RHR: {rhr_reason}")
    if recovery_reason:
        factors.append(recovery_reason)
    if user_profile.get("rhr"):
        factors.append(f"Using profile baseline RHR={user_profile['rhr']} bpm")

    return {
        "score": score,
        "ratio": round(ratio, 2),
        "detail": f"Readiness {score.lower()} ({total}/{max_possible})",
        "contributing_factors": factors,
    }


# ---------------------------------------------------------------------------
# Overall status
# ---------------------------------------------------------------------------

def determine_overall_status(readiness: dict, fatigue: dict,
                             training_status: dict) -> str:
    """Map readiness x fatigue x training_status to a final status label."""
    r_score = readiness.get("score", "Moderate")
    f_level = fatigue.get("level", "Normal")
    t_state = training_status.get("state", "Insufficient Data")

    if r_score == "Ready" and f_level == "Fresh" and t_state == "Performance":
        return "Race Ready"
    if f_level == "Overtrained" or r_score == "Rest" or t_state == "Excessive":
        return "Rest Day Recommended"
    if r_score == "Recover":
        return "Recovery Needed"
    if r_score in ("Ready", "Moderate") and f_level in ("Fresh", "Normal"):
        return "Ready to Train"
    if r_score == "Moderate" or f_level == "Fatigued":
        return "Proceed with Caution"
    return "Ready to Train"
