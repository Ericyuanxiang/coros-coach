"""Safety analysis — guardrails, alerts, evidence summary."""

from . import _avg
from .thresholds import (
    HRV_ALERT_STREAK,
    HRV_ALERT_THRESHOLD,
    SLEEP_OPTIMAL_MINUTES,
    SLEEP_DEBT_ALERT_HOURS,
    RHR_ELEVATED_ALERT_BPM,
    INACTIVITY_DAYS,
    DAYS_SINCE_TRAINING_RETURN,
    SLEEP_DEBT_CAUTION,
    SLEEP_MIN_ATHLETE,
    RHR_ELEVATED_CAUTION,
    HIGH_LOAD_DAYS,
    RETURN_VOLUME_FACTOR,
    INTENSITY_RANK,
)


# ---------------------------------------------------------------------------
# 1. Guardrails
# ---------------------------------------------------------------------------

def _cap_intensity(current: str, cap: str) -> str:
    """Clamp intensity to at most `cap` using explicit rank."""
    if INTENSITY_RANK.get(current, 0) <= INTENSITY_RANK.get(cap, 1):
        return current
    return cap


def build_training_guardrails(
    readiness: dict,
    fatigue: dict,
    training_status: dict,
    hrv: dict,
    sleep: dict,
    freshness: dict,
    daily_records: list[dict] | None = None,
) -> dict:
    """Build evidence-based hard constraints and soft cautions for training."""
    daily_records = daily_records or []
    r_score = readiness.get("score", "Moderate")
    f_level = fatigue.get("level", "Normal")
    days_since = freshness.get("days_since_training")

    forbidden: list[str] = []
    caution: list[str] = []
    intensity = "Moderate"
    duration = [30, 60]

    # CRITICAL: overtrained or readiness critically low
    if f_level == "Overtrained":
        forbidden.append("All training — fatigue assessment: Overtrained")
        intensity = "Rest"
        duration = [0, 0]
    if r_score == "Rest":
        forbidden.append("All training — readiness critically low")
        intensity = "Rest"
        duration = [0, 0]

    if intensity == "Rest":
        return {
            "allowed_intensity": intensity,
            "duration_range_minutes": duration,
            "forbidden": forbidden,
            "caution": caution,
            "risk_level": "high",
            "return_to_training_phase": None,
        }

    # High training load
    high_load_streak = 0
    for r in daily_records[:7]:
        rs = r.get("training_load_ratio_state")
        if rs == 3:
            high_load_streak += 1
        else:
            break
    if high_load_streak >= HIGH_LOAD_DAYS:
        forbidden.append(
            "Moderate or higher intensity — training load ratio "
            "consecutively high, deload recommended")
        intensity = "Easy"
        duration = [20, 45]

    # Detraining / return-to-training
    if days_since is not None and days_since > DAYS_SINCE_TRAINING_RETURN:
        forbidden.append(
            f"High intensity / intervals / long runs — {days_since} days "
            f"detraining, follow 50% rule (Mujika & Padilla, 2000)")
        intensity = _cap_intensity(intensity, "Easy")
        duration = [max(duration[0], 20), min(duration[1], 45)]
        caution.append(
            f"Return-to-training protocol: start at "
            f"{RETURN_VOLUME_FACTOR * 100:.0f}% of previous volume, "
            f"progress gradually over 8-12 weeks")

    # Sleep caution
    sleep_avg = sleep.get("avg_duration_hours")
    sleep_debt = sleep.get("debt_hours") or 0
    if sleep_avg is not None and sleep_avg < SLEEP_MIN_ATHLETE:
        forbidden.append(
            f"All training — sleep avg {sleep_avg:.1f}h < "
            f"{SLEEP_MIN_ATHLETE}h minimum, injury risk 1.7x (Hatia 2024)")
        intensity = "Rest"
        duration = [0, 0]
    elif sleep_debt >= SLEEP_DEBT_CAUTION:
        caution.append(
            f"Sleep debt {sleep_debt:.1f}h — prioritize sleep, "
            f"avoid hard evening sessions")

    # HRV caution
    hrv_deviation = hrv.get("deviation_pct") or 0
    if hrv_deviation < -25:
        caution.append(
            f"HRV significantly below baseline ({hrv_deviation:+.0f}%) — "
            f"autonomic recovery incomplete")

    # RHR caution
    rhrs = [(r.get("rhr"), r.get("date")) for r in daily_records
            if r.get("rhr") is not None]
    if len(rhrs) >= 2:
        latest_rhr = rhrs[0][0]
        week_avg = _avg([h for h, _ in rhrs[1:7]])
        if (week_avg is not None
                and latest_rhr > week_avg + RHR_ELEVATED_CAUTION):
            caution.append(
                f"RHR elevated {latest_rhr - week_avg:.0f} bpm above 7d avg")

    # Risk level
    if forbidden:
        risk_level = "high"
    elif caution:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "allowed_intensity": intensity,
        "duration_range_minutes": duration,
        "forbidden": forbidden,
        "caution": caution,
        "risk_level": risk_level,
        "return_to_training_phase": (
            "return_to_play" if (days_since and days_since > 14) else None),
    }


# ---------------------------------------------------------------------------
# 2. Alerts
# ---------------------------------------------------------------------------

def generate_alerts(
    daily_records: list[dict],
    sleep_records: list[dict],
    training_status: dict,
    hrv: dict,
    fatigue: dict,
) -> list[str]:
    """Check for actionable warning signals. Returns list of alert strings."""
    alerts: list[str] = []

    # HRV below baseline for N+ consecutive days
    hrvs = [(r.get("avg_sleep_hrv"), r.get("baseline"), r.get("date"))
            for r in daily_records if r.get("avg_sleep_hrv") is not None]
    if len(hrvs) >= HRV_ALERT_STREAK:
        baseline = hrvs[0][1] or _avg([h for h, _, _ in hrvs])
        streak = 0
        for hrv_val, _, _ in hrvs:
            if baseline and baseline > 0:
                dev = ((hrv_val - baseline) / baseline) * 100
                if dev < HRV_ALERT_THRESHOLD:
                    streak += 1
                else:
                    break
            else:
                break
        if streak >= HRV_ALERT_STREAK:
            alerts.append(
                f"HRV below baseline for {streak} consecutive days — "
                f"nervous system may be under-recovered")

    # Sleep debt > threshold
    if sleep_records and sleep_records[:3]:
        recent_dur = _avg([r.get("total_duration_minutes")
                           for r in sleep_records[:3]])
        if recent_dur is not None:
            debt_hours = (SLEEP_OPTIMAL_MINUTES - recent_dur) / 60
            if debt_hours >= SLEEP_DEBT_ALERT_HOURS:
                alerts.append(
                    f"Sleep debt of {debt_hours:.1f}h over last 3 nights — "
                    f"prioritize sleep")

    # High training load ratio for 3+ days
    high_load_streak = 0
    for r in daily_records[:7]:
        if r.get("training_load_ratio_state") == 3:
            high_load_streak += 1
        else:
            break
    if high_load_streak >= 3:
        alerts.append(
            f"Training load ratio in 'High' zone for {high_load_streak} "
            f"consecutive days — consider deload")

    # Inactivity
    training_days = [r for r in daily_records
                     if r.get("training_load")
                     and r.get("training_load", 0) > 0]
    if len(daily_records) >= INACTIVITY_DAYS and not training_days:
        total_days = len([r for r in daily_records if r.get("date")])
        if total_days >= INACTIVITY_DAYS:
            alerts.append(
                f"No training recorded in {total_days}+ days — "
                f"may be losing fitness")

    # RHR elevated
    rhrs = [(r.get("rhr"), r.get("date")) for r in daily_records
            if r.get("rhr") is not None]
    if len(rhrs) >= 2:
        latest_rhr = rhrs[0][0]
        week_avg = _avg([h for h, _ in rhrs[1:7]])
        if (week_avg is not None
                and latest_rhr > week_avg + RHR_ELEVATED_ALERT_BPM):
            alerts.append(
                f"RHR elevated {latest_rhr - week_avg:.0f} bpm above 7d avg "
                f"— possible overtraining or illness")

    # Overtrained fatigue
    if fatigue.get("level") == "Overtrained":
        alerts.append(
            "Fatigue assessment: Overtrained — extended rest recommended")

    return alerts


# ---------------------------------------------------------------------------
# 3. Evidence Summary
# ---------------------------------------------------------------------------

def build_evidence_summary(
    readiness: dict,
    fatigue: dict,
    hrv: dict,
    sleep: dict,
    training_status: dict,
    freshness: dict,
    recent_training: dict,
) -> list[dict]:
    """Generate structured, evidence-cited observations from deterministic rules."""
    observations: list[dict] = []

    # Detraining
    days_since = freshness.get("days_since_training")
    last_training = freshness.get("last_training_date")
    if days_since is not None and days_since > 14:
        vo2_loss = "12-20%" if days_since <= 28 else "20%+"
        observations.append({
            "level": "critical",
            "title": f"Detrained {days_since} days",
            "detail": (
                f"Last training: {last_training}. Estimated VO2max loss: "
                f"{vo2_loss}, connective tissue tolerance significantly "
                f"reduced. Requires 8-12 weeks gradual return "
                f"(Mujika & Padilla, 2000)."
            ),
        })
    elif days_since is not None and days_since > 5:
        observations.append({
            "level": "warning",
            "title": f"Training break {days_since} days",
            "detail": (
                f"Short break — blood volume may have decreased, "
                f"VO2max down ~4-7%. Recovery to baseline ~1 week."
            ),
        })

    # Sleep
    sleep_avg = sleep.get("avg_duration_hours")
    sleep_debt = sleep.get("debt_hours") or 0
    if sleep_avg is not None and sleep_avg < 5:
        observations.append({
            "level": "critical",
            "title": "Severe sleep deprivation",
            "detail": (
                f"3-night avg {sleep_avg:.1f}h, far below athlete "
                f"recommendation 9-10h. <5h sleep: injury risk 1.7x "
                f"(Hatia et al., 2024)."
            ),
        })
    elif sleep_debt >= 2:
        observations.append({
            "level": "warning",
            "title": f"Sleep debt {sleep_debt:.1f}h",
            "detail": (
                f"Cumulative {sleep_debt:.1f}h deficit over 3 nights. "
                f"Growth hormone secretion depends on deep sleep."
            ),
        })
    elif sleep_avg is not None and sleep_avg >= 7:
        observations.append({
            "level": "info",
            "title": f"Adequate sleep ({sleep_avg:.1f}h/night)",
            "detail": "Sleep duration within normal range.",
        })

    # HRV
    hrv_deviation = hrv.get("deviation_pct") or 0
    hrv_status = hrv.get("status", "Normal")
    hrv_trend = hrv.get("trend", "Stable")
    if hrv_status == "Low":
        observations.append({
            "level": "warning",
            "title": f"HRV low (deviation {hrv_deviation:+.0f}%)",
            "detail": (
                "RMSSD below individual baseline — sympathetic dominance. "
                "HRV-guided training outperforms fixed plans "
                "(Addleman et al., 2024)."
            ),
        })
    else:
        observations.append({
            "level": "info",
            "title": f"HRV normal (deviation {hrv_deviation:+.0f}%)",
            "detail": "Autonomic nervous system not showing significant stress.",
        })

    # RHR
    r_contribs = readiness.get("contributing_factors", [])
    for c in r_contribs:
        if "RHR" in c and "elevated" in c.lower():
            observations.append({
                "level": "warning",
                "title": "RHR elevated",
                "detail": f"{c}. Cross-reference with HRV for full picture.",
            })
            break

    # Training load
    t_state = training_status.get("state", "Insufficient Data")
    t28d = training_status.get("base_fitness")
    t7d = training_status.get("load_impact")
    if t28d and t7d is not None and t28d > 0:
        ratio = t7d / t28d * 100 if t28d > 0 else 0
        if ratio < 5 and days_since and days_since > 10:
            observations.append({
                "level": "info",
                "title": "Very low training load",
                "detail": (
                    f"7d load {t7d} vs 28d fitness {t28d} ({ratio:.0f}%). "
                    f"Maintenance requires 2x/week stimulus."
                ),
            })

    # Fatigue
    f_level = fatigue.get("level", "Normal")
    if f_level == "Fatigued":
        observations.append({
            "level": "warning",
            "title": "Fatigue: Fatigued",
            "detail": "Multiple fatigue signals cross-validated as fatigued.",
        })

    # Training content
    total_sessions = recent_training.get("total_sessions", 0)
    by_sport = recent_training.get("by_sport", {})
    if total_sessions > 0:
        sport_lines = []
        for sport, stats in by_sport.items():
            sport_lines.append(
                f"{sport} {stats['sessions']}x "
                f"({stats['distance_km']:.1f}km, {stats['duration_min']:.0f}min)")
        observations.append({
            "level": "info",
            "title": f"Recent training ({total_sessions} sessions)",
            "detail": "; ".join(sport_lines) if sport_lines
            else "No detail available",
        })

    return observations
