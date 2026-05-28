"""Recovery analysis — HRV trends and sleep trends."""

from . import _avg, _trend
from .thresholds import (
    HRV_GOOD_THRESHOLD,
    HRV_FAIR_THRESHOLD,
    SLEEP_OPTIMAL_MINUTES,
)


def analyze_hrv_trend(daily_records: list[dict]) -> dict:
    """Analyze HRV: 7-day trend, baseline deviation, status.

    Returns dict with: latest, seven_day_avg, baseline, trend, status, deviation_pct.
    """
    hrvs = [(r.get("avg_sleep_hrv"), r.get("baseline"), r.get("date"))
            for r in daily_records if r.get("avg_sleep_hrv") is not None]

    if len(hrvs) < 3:
        baseline = _avg([h for h, _, _ in hrvs])
        latest_hrv = hrvs[0][0] if hrvs else None
        deviation = round(((latest_hrv - baseline) / baseline) * 100, 1) if (
            latest_hrv and baseline and baseline != 0) else 0
        return {"latest": latest_hrv,
                "seven_day_avg": _avg([h for h, _, _ in hrvs]),
                "baseline": baseline, "trend": "Stable",
                "status": "Insufficient Data",
                "deviation_pct": deviation if isinstance(deviation, (int, float))
                else None}

    latest_hrv, baseline, _ = hrvs[0]
    recent_vals = [h for h, _, _ in hrvs[:3]]
    previous_vals = [h for h, _, _ in hrvs[3:7]]

    seven_day_avg = _avg([h for h, _, _ in hrvs[:7]])
    baseline = baseline or _avg([h for h, _, _ in hrvs])
    recent_avg = _avg(recent_vals)
    previous_avg = _avg(previous_vals) if previous_vals else recent_avg

    trend = _trend(recent_avg, previous_avg)

    if baseline and baseline > 0:
        deviation = ((latest_hrv - baseline) / baseline) * 100
    else:
        deviation = 0

    if deviation > -HRV_GOOD_THRESHOLD * 1.5:
        status = "High" if deviation > 15 else "Normal"
    elif deviation < HRV_FAIR_THRESHOLD:
        status = "Low"
    else:
        status = "Normal"

    return {
        "latest": latest_hrv,
        "seven_day_avg": round(seven_day_avg, 1) if seven_day_avg else None,
        "baseline": baseline,
        "trend": trend,
        "status": status,
        "deviation_pct": round(deviation, 1),
    }


def analyze_sleep_trend(sleep_records: list[dict]) -> dict:
    """Analyze sleep: 7-day duration/quality trend and sleep debt.

    Returns dict with: avg_duration_hours, quality_score, trend, debt_hours.
    """
    if not sleep_records:
        return {"avg_duration_hours": None, "quality_score": None,
                "trend": "Stable", "debt_hours": 0}

    recent = sleep_records[:3]
    previous = sleep_records[3:7]

    avg_dur = _avg([r.get("total_duration_minutes") for r in sleep_records[:7]])
    avg_qual = _avg([qs for r in sleep_records[:7]
                     if (qs := r.get("quality_score")) is not None and qs >= 0])
    recent_dur = _avg([r.get("total_duration_minutes") for r in recent])
    previous_dur = _avg([r.get("total_duration_minutes") for r in previous])

    trend = _trend(recent_dur, previous_dur)
    if recent_dur is not None and recent_dur > (previous_dur or recent_dur):
        trend = "Improving"
    elif recent_dur is not None and recent_dur < (previous_dur or recent_dur):
        trend = "Declining"

    debt = (SLEEP_OPTIMAL_MINUTES - (recent_dur or SLEEP_OPTIMAL_MINUTES)) / 60
    debt = max(0, round(debt, 1))

    return {
        "avg_duration_hours": round(avg_dur / 60, 1) if avg_dur else None,
        "quality_score": round(avg_qual, 1) if avg_qual else None,
        "trend": trend,
        "debt_hours": debt,
    }
