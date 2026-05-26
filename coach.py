"""Coach briefing analysis engine — pure functions, no I/O."""

from statistics import mean
from typing import Any

# ---------------------------------------------------------------------------
# Thresholds (tune these constants for your athletes)
# ---------------------------------------------------------------------------

# HRV
HRV_GOOD_THRESHOLD = -10     # deviation % from baseline — above this is Good
HRV_FAIR_THRESHOLD = -25     # below this is Poor; between = Fair
HRV_ALERT_THRESHOLD = -15    # consecutive days below this → alert
HRV_ALERT_STREAK = 3         # how many consecutive bad days trigger alert

# Sleep
SLEEP_OPTIMAL_MINUTES = 480  # 8 hours
SLEEP_GOOD_MINUTES = 420     # 7 hours → Good
SLEEP_FAIR_MINUTES = 360     # 6 hours → Fair
SLEEP_GOOD_QUALITY = 70
SLEEP_FAIR_QUALITY = 50
SLEEP_DEBT_ALERT_HOURS = 2   # debt > this over 3 nights → alert

# Resting HR
RHR_ELEVATED_BPM = 3         # bpm above 7d avg → point deduction
RHR_ELEVATED_ALERT_BPM = 5   # bpm above 7d avg → alert

# Fatigue (tired_rate numeric fallback zones)
FRESH_TIRED_RATE = -30
FATIGUED_TIRED_RATE = 0
OVERTRAINED_TIRED_RATE = 20

# Trends
TREND_PCT = 5.0              # min % change to call a trend Rising or Falling
STAMINA_TREND_PCT = 2.0

# Inactivity
INACTIVITY_DAYS = 5          # days without training → alert


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return mean(clean) if clean else None

def _trend(recent: float | None, previous: float | None, threshold_pct: float = TREND_PCT) -> str:
    """Return Rising / Stable / Falling based on % change between two averages."""
    if recent is None or previous is None or previous == 0:
        return "Stable"
    change = ((recent - previous) / abs(previous)) * 100
    if change > threshold_pct:
        return "Rising"
    if change < -threshold_pct:
        return "Falling"
    return "Stable"


# ---------------------------------------------------------------------------
# 1. assess_readiness
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

    if baseline and baseline > 0:
        deviation = ((latest_hrv - baseline) / baseline) * 100
    else:
        deviation = 0

    if deviation > HRV_GOOD_THRESHOLD:
        return 2, f"HRV {deviation:+.0f}% vs baseline → Good (2 pts)"
    if deviation > HRV_FAIR_THRESHOLD:
        return 1, f"HRV {deviation:+.0f}% vs baseline → Fair (1 pt)"
    return 0, f"HRV {deviation:+.0f}% vs baseline → Poor (0 pts)"


def _sleep_score(sleep_records: list[dict]) -> tuple[int | None, str]:
    """Return (points, reason). 0–2 pts, or None if no sleep data."""
    if not sleep_records:
        return None, "No sleep data available → skipped"

    recent = sleep_records[:3]
    dur = _avg([r.get("total_duration_minutes") for r in recent])
    qual = _avg([r.get("quality_score") for r in recent if r.get("quality_score", -1) >= 0])

    if dur is None:
        return None, "No sleep duration data → skipped"

    if dur >= SLEEP_GOOD_MINUTES and (qual is None or qual >= SLEEP_GOOD_QUALITY):
        return 2, f"Sleep avg {dur/60:.1f}h (quality {qual:.0f}) → Good (2 pts)"
    if dur >= SLEEP_FAIR_MINUTES and (qual is None or qual >= SLEEP_FAIR_QUALITY):
        return 1, f"Sleep avg {dur/60:.1f}h (quality {qual:.0f}) → Fair (1 pt)"
    return 0, f"Sleep avg {dur/60:.1f}h (quality {qual}) → Poor (0 pts)"


def _rhr_score(daily_records: list[dict], rhr_baseline: int | None = None) -> tuple[int | None, str]:
    """Return (points, reason). -1 to +1 pt, or None if no RHR data.

    When rhr_baseline (from user profile) is provided, it serves as a more
    reliable reference than the 7-day rolling average.
    """
    rhrs = [(r.get("rhr"), r.get("date")) for r in daily_records if r.get("rhr") is not None]
    if not rhrs:
        return None, "No RHR data available → skipped"

    latest_rhr = rhrs[0][0]
    week_avg = _avg([h for h, _ in rhrs[1:7]])

    # Prefer profile baseline (stable), fall back to week_avg (noisy)
    baseline = rhr_baseline if rhr_baseline else week_avg
    baseline_label = "profile baseline" if rhr_baseline else "7d avg"
    if baseline is None:
        return 0, "Not enough RHR history for baseline → neutral (0 pts)"

    if latest_rhr <= baseline:
        return 1, f"RHR {latest_rhr} ≤ {baseline_label} {baseline:.0f} → Recovered (+1 pt)"
    if latest_rhr <= baseline + RHR_ELEVATED_BPM:
        return 0, f"RHR {latest_rhr} slightly above {baseline_label} {baseline:.0f} → Neutral (0 pts)"
    return -1, f"RHR {latest_rhr} elevated vs {baseline_label} {baseline:.0f} → Elevated (-1 pt)"


def assess_readiness(
    daily_records: list[dict],
    sleep_records: list[dict],
    user_profile: dict | None = None,
    recovery_hours: int | None = None,
) -> dict:
    """Evaluate training readiness from HRV, sleep, resting HR, and Coros recovery.

    Scoring denominations: HRV 0-2, Sleep 0-2, RHR -1-+1.
    Recovery hours (from Coros dashboard) acts as a cap: if still recovering,
    readiness is capped at Moderate regardless of other signals.

    Returns dict with: score (Ready/Moderate/Recover/Rest), contributing_factors.
    """
    user_profile = user_profile or {}
    rhr_baseline = user_profile.get("rhr")
    hrv_pts, hrv_reason = _hrv_score(daily_records)
    sleep_pts, sleep_reason = _sleep_score(sleep_records)
    rhr_pts, rhr_reason = _rhr_score(daily_records, rhr_baseline)

    max_denominator = (2 if hrv_pts is not None else 0) + (2 if sleep_pts is not None else 0) + (1 if rhr_pts is not None else 0)
    total = (hrv_pts or 0) + (sleep_pts or 0) + (rhr_pts or 0)

    if max_denominator == 0:
        ratio = 0.5  # no data at all -> default Moderate
    else:
        ratio = total / max_denominator

    # Recovery hours cap: if Coros says recovery not complete, cap at Moderate
    recovery_factor = None
    if recovery_hours is not None:
        if recovery_hours <= 0:
            recovery_factor = f"Recovery complete (0h remaining) -> no cap"
        elif recovery_hours <= 4:
            recovery_factor = f"Recovery nearly complete ({recovery_hours}h remaining) -> slight cap"
            ratio = min(ratio, 0.75)
        elif recovery_hours <= 12:
            recovery_factor = f"Still recovering ({recovery_hours}h remaining) -> capped at Moderate"
            ratio = min(ratio, 0.6)
        else:
            recovery_factor = f"Recovery needed ({recovery_hours}h remaining) -> capped at Recover"
            ratio = min(ratio, 0.4)

    if ratio >= 0.8:
        score = "Ready"
    elif ratio >= 0.4:
        score = "Moderate"
    elif ratio >= 0.2:
        score = "Recover"
    else:
        score = "Rest"

    factors = [r for r in (hrv_reason, sleep_reason, rhr_reason, recovery_factor) if r is not None]

    return {"score": score, "ratio": round(ratio, 2), "contributing_factors": factors}


# ---------------------------------------------------------------------------
# 2. assess_fatigue
# ---------------------------------------------------------------------------

def _tired_rate_signal(daily_records: list[dict]) -> tuple[str, str]:
    """Fatigue signal from Coros tired_rate. (level, reason)."""
    for r in daily_records:
        state = r.get("tired_rate_state_new")
        tired = r.get("tired_rate")
        if state is not None or tired is not None:
            break
    else:
        return "Normal", "No tired_rate data → default Normal"

    # Prefer enum, fall back to numeric
    if state is not None:
        mapping = {1: "Fresh", 2: "Normal", 3: "Fatigued"}
        label = mapping.get(state, "Normal")
        return label, f"Coros fatigue state = {state} → {label}"

    if tired is not None:
        if tired < FRESH_TIRED_RATE:
            return "Fresh", f"tired_rate {tired} < {FRESH_TIRED_RATE} → Fresh"
        if tired < FATIGUED_TIRED_RATE:
            return "Normal", f"tired_rate {tired} in [{FRESH_TIRED_RATE}, {FATIGUED_TIRED_RATE}) → Normal"
        if tired < OVERTRAINED_TIRED_RATE:
            return "Fatigued", f"tired_rate {tired} in [{FATIGUED_TIRED_RATE}, {OVERTRAINED_TIRED_RATE}) → Fatigued"
        return "Overtrained", f"tired_rate {tired} ≥ {OVERTRAINED_TIRED_RATE} → Overtrained"

    return "Normal", "No tired_rate data → default Normal"


def _sleep_debt_signal(sleep_records: list[dict]) -> tuple[str, str] | None:
    """Fatigue signal from sleep debt. Returns (level, reason) or None."""
    if not sleep_records:
        return None

    recent = sleep_records[:3]
    dur = _avg([r.get("total_duration_minutes") for r in recent])
    if dur is None:
        return None

    if dur >= SLEEP_GOOD_MINUTES:
        return "Fresh", f"Recent sleep avg {dur/60:.1f}h → Fresh"
    if dur >= SLEEP_FAIR_MINUTES:
        return "Normal", f"Recent sleep avg {dur/60:.1f}h → Normal"
    return "Fatigued", f"Recent sleep avg {dur/60:.1f}h → Fatigued"


def _hrv_fatigue_signal(daily_records: list[dict]) -> tuple[str, str] | None:
    """Fatigue signal from HRV deviation. Returns (level, reason) or None."""
    hrvs = [(r.get("avg_sleep_hrv"), r.get("baseline")) for r in daily_records
            if r.get("avg_sleep_hrv") is not None]
    if len(hrvs) == 0:
        return None

    latest_hrv, baseline = hrvs[0]
    if baseline is None:
        baseline = _avg([h for h, _ in hrvs])
    if baseline is None or baseline == 0:
        return None

    deviation = ((latest_hrv - baseline) / baseline) * 100

    if deviation > HRV_GOOD_THRESHOLD:
        return "Fresh", f"HRV {deviation:+.0f}% vs baseline → Fresh"
    if deviation > HRV_FAIR_THRESHOLD:
        return "Normal", f"HRV {deviation:+.0f}% vs baseline → Normal"
    return "Fatigued", f"HRV {deviation:+.0f}% vs baseline → Fatigued"


def _stress_signal(daily_health: list[dict]) -> tuple[str, str] | None:
    """Fatigue signal from stress data (mobile API). Returns (level, reason) or None."""
    if not daily_health:
        return None
    stresses = [r.get("avg_stress") for r in daily_health[:7]
                if r.get("avg_stress") is not None]
    if len(stresses) < 3:
        return None
    avg = _avg(stresses)
    if avg is None:
        return None
    if avg < 30:
        return "Fresh", f"Avg stress {avg:.0f}/100 (low) -> Fresh"
    if avg < 50:
        return "Normal", f"Avg stress {avg:.0f}/100 (moderate) -> Normal"
    return "Fatigued", f"Avg stress {avg:.0f}/100 (high) -> Fatigued"


def assess_fatigue(
    daily_records: list[dict],
    sleep_records: list[dict] | None = None,
    daily_health: list[dict] | None = None,
) -> dict:
    """Fuse four fatigue signals (tired_rate, sleep debt, HRV deviation, stress).

    Majority vote with overtrained override.
    Returns dict with: level, fatigue_rate, contributing_factors.
    """
    sleep_records = sleep_records or []
    daily_health = daily_health or []

    tr_level, tr_reason = _tired_rate_signal(daily_records)
    sleep_result = _sleep_debt_signal(sleep_records)
    hrv_result = _hrv_fatigue_signal(daily_records)
    stress_result = _stress_signal(daily_health)

    signals: list[tuple[str, str]] = [(tr_level, tr_reason)]
    if sleep_result:
        signals.append(sleep_result)
    if hrv_result:
        signals.append(hrv_result)
    if stress_result:
        signals.append(stress_result)

    levels = [s[0] for s in signals]

    if "Overtrained" in levels:
        level = "Overtrained"
    elif levels.count("Fatigued") >= 2 or levels.count("Overtrained") >= 1:
        level = "Overtrained" if "Overtrained" in levels else "Fatigued"
    elif levels.count("Fresh") >= 2:
        level = "Fresh"
    elif levels.count("Fatigued") >= 1:
        level = "Fatigued"
    elif levels.count("Fresh") >= 1 and levels.count("Normal") >= 1:
        level = "Normal"
    elif "Normal" in levels:
        level = "Normal"
    else:
        level = "Fresh"

    fatigue_rate = None
    for r in daily_records:
        fatigue_rate = r.get("tired_rate")
        if fatigue_rate is not None:
            break

    return {
        "level": level,
        "fatigue_rate": fatigue_rate,
        "contributing_factors": [s[1] for s in signals],
    }


# ---------------------------------------------------------------------------
# 3. compute_training_status
# ---------------------------------------------------------------------------

def compute_training_status(daily_records: list[dict]) -> dict:
    """Determine training status using Coros EvoLab data (CSB model).

    Uses training_load_ratio_state (1=Low, 2=Optimal, 3=High) and stamina trend.
    Returns dict with: state, base_fitness, load_impact, intensity_trend, training_load_ratio.
    """
    if not daily_records:
        return {"state": "Insufficient Data", "base_fitness": None, "load_impact": None,
                "intensity_trend": "Stable", "training_load_ratio": None}

    latest = daily_records[0]
    rstate = latest.get("training_load_ratio_state")
    stamina = latest.get("stamina_level")
    stamina_7d = latest.get("stamina_level_7d")
    t7d = latest.get("t7d")
    t28d = latest.get("t28d")

    stamina_trend = _trend(stamina_7d, stamina, STAMINA_TREND_PCT)

    if rstate == 3:
        state = "Excessive"
    elif rstate == 2 and stamina_trend == "Rising":
        state = "Performance"
    elif rstate == 2:
        state = "Optimized"
    elif rstate == 1 and (t7d or 0) > 0:
        state = "Maintaining"
    elif rstate == 1:
        state = "Resuming"
    else:
        state = "Insufficient Data"

    return {
        "state": state,
        "base_fitness": t28d,
        "load_impact": t7d,
        "intensity_trend": stamina_trend,
        "training_load_ratio": latest.get("training_load_ratio"),
    }


# ---------------------------------------------------------------------------
# 4. analyze_hrv_trend
# ---------------------------------------------------------------------------

def analyze_hrv_trend(daily_records: list[dict]) -> dict:
    """Analyze HRV: 7-day trend, baseline deviation, status.

    Returns dict with: latest, seven_day_avg, baseline, trend, status, deviation_pct.
    """
    hrvs = [(r.get("avg_sleep_hrv"), r.get("baseline"), r.get("date"))
            for r in daily_records if r.get("avg_sleep_hrv") is not None]

    if len(hrvs) < 3:
        baseline = _avg([h for h, _, _ in hrvs])
        latest_hrv = hrvs[0][0] if hrvs else None
        deviation = round(((latest_hrv - baseline) / baseline) * 100, 1) if (latest_hrv and baseline and baseline != 0) else 0
        return {"latest": latest_hrv, "seven_day_avg": _avg([h for h, _, _ in hrvs]),
                "baseline": baseline, "trend": "Stable", "status": "Insufficient Data",
                "deviation_pct": deviation if isinstance(deviation, (int, float)) else None}

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


# ---------------------------------------------------------------------------
# 5. analyze_sleep_trend
# ---------------------------------------------------------------------------

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
    avg_qual = _avg([r.get("quality_score") for r in sleep_records[:7]
                     if r.get("quality_score", -1) >= 0])
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


# ---------------------------------------------------------------------------
# 6. compute_weekly_comparison
# ---------------------------------------------------------------------------

def compute_weekly_comparison(daily_records: list[dict]) -> dict:
    """Compare this week (last 7 days) to last week (days 7-13).

    Returns dict with: this_week_load, last_week_load, load_change_pct,
    total_duration_hours, total_distance_km, sessions_completed.
    """
    this_week = daily_records[:7]
    last_week = daily_records[7:14]

    def sum_week(records):
        loads = [r.get("training_load") for r in records if r.get("training_load")]
        durations = [r.get("duration") for r in records if r.get("duration")]
        distances = [r.get("distance") for r in records if r.get("distance")]
        sessions = len([r for r in records if r.get("training_load") or r.get("duration")])
        return {
            "load": sum(loads) if loads else 0,
            "duration_hours": sum(durations) / 3600 if durations else 0,
            "distance_km": sum(distances) / 1000 if distances else 0,
            "sessions": sessions,
        }

    tw = sum_week(this_week)
    lw = sum_week(last_week)

    if lw["load"] > 0:
        change = round(((tw["load"] - lw["load"]) / lw["load"]) * 100, 1)
    elif tw["load"] > 0:
        change = 100.0
    else:
        change = 0.0

    return {
        "this_week_load": tw["load"],
        "last_week_load": lw["load"],
        "load_change_pct": change,
        "total_duration_hours": round(tw["duration_hours"], 1),
        "total_distance_km": round(tw["distance_km"], 1),
        "sessions_completed": tw["sessions"],
    }


# ---------------------------------------------------------------------------
# 7. generate_recommendation
# ---------------------------------------------------------------------------

def _zone_target(intensity: str, user_profile: dict) -> dict | None:
    """Build personalized HR zone target from user profile, or None if unavailable."""
    zone_model = user_profile.get("hr_zone_type", 1) or 1
    zones = (user_profile.get("zones") or {}).get(zone_model)
    if not zones:
        return None

    # Map intensity to zone index (1-indexed, Coros uses 6 zones)
    zone_map = {"Rest": 0, "Easy": 2, "Moderate": 3, "Hard": 5}
    zone_idx = zone_map.get(intensity, 2)
    try:
        entry = zones[zone_idx - 1]
    except (IndexError, TypeError):
        return None
    low = entry.get("hrLow")
    high = entry.get("hrHigh")
    if low and high:
        return {"zone": zone_idx, "model": {1: "MaxHR", 2: "%HRR", 3: "%LTHR"}.get(zone_model, "MaxHR"),
                "bpm_low": low, "bpm_high": high}
    return None


def generate_recommendation(
    readiness: dict,
    fatigue: dict,
    training_status: dict,
    schedule: list[dict] | None = None,
    user_profile: dict | None = None,
) -> dict:
    """Generate today's training recommendation from readiness × fatigue × status.

    When user_profile is provided, includes personalized heart rate zone targets.
    Returns dict with: primary, alternative, intensity, duration_minutes, why, zone_target.
    """
    user_profile = user_profile or {}
    r_score = readiness.get("score", "Moderate")
    f_level = fatigue.get("level", "Normal")
    t_state = training_status.get("state", "Insufficient Data")

    # Decision matrix
    if f_level == "Overtrained" or t_state == "Excessive":
        intensity, dur, primary, why = "Rest", 0, "Complete rest — overtraining or excessive load signals", "Overtraining/excessive load indicators present"
    elif r_score == "Recover":
        intensity, dur, primary, why = "Easy", 30, "Active recovery — very low intensity or full rest", "Readiness is low, prioritize recovery"
    elif r_score == "Rest":
        intensity, dur, primary, why = "Rest", 0, "Full rest day recommended", "Readiness critically low"
    elif r_score == "Ready" and f_level == "Fresh" and t_state == "Performance":
        intensity, dur, primary, why = "Hard", 75, "Race-specific session or high-intensity intervals", "Peak performance window — great day for quality work"
    elif r_score == "Ready" and (f_level == "Fresh" or f_level == "Normal") and t_state == "Optimized":
        intensity, dur, primary, why = "Hard", 60, "Threshold/tempo session — good day for hard training", "Optimal training zone with adequate recovery"
    elif r_score == "Ready" and f_level == "Fresh" and t_state == "Maintaining":
        intensity, dur, primary, why = "Moderate", 60, "Moderate build session — progressive medium-long run", "Solid fitness base, building volume"
    elif r_score == "Ready" and f_level == "Normal" and t_state == "Maintaining":
        intensity, dur, primary, why = "Moderate", 50, "Standard training day — quality but not max effort", "Normal readiness with maintained fitness"
    elif r_score == "Ready" and f_level == "Fatigued":
        intensity, dur, primary, why = "Easy", 45, "Active recovery or easy run — monitor how you feel", "Ready signals are good but fatigue is present"
    elif r_score == "Moderate" and (f_level == "Fresh" or f_level == "Normal") and t_state == "Optimized":
        intensity, dur, primary, why = "Moderate", 60, "Technique-focused session — moderate intensity with form emphasis", "Moderate readiness, optimized training zone"
    elif r_score == "Moderate":
        intensity, dur, primary, why = "Easy", 45, "Easy run or cross-training — keep it light", "Moderate readiness — focus on consistency, not intensity"
    elif t_state == "Resuming":
        intensity, dur, primary, why = "Easy", 30, "Ease back in — short, easy session", "Resuming training — gradual return"
    else:
        intensity, dur, primary, why = "Moderate", 50, "Standard training day", "Default recommendation — listen to your body"

    # Personalized zone target from user profile (HR zones)
    zone_target = _zone_target(intensity, user_profile)

    # Alternative: if the user has a scheduled workout today, note it
    alternative = None
    if schedule:
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        for entity in schedule if isinstance(schedule, list) else schedule.get("entities", []):
            if isinstance(entity, dict) and entity.get("happenDay") == today:
                alt_name = entity.get("name") or "Scheduled workout"
                alternative = f"Today's plan: {alt_name} — adjust based on readiness ({r_score})"
                break

    result = {
        "primary": primary,
        "alternative": alternative,
        "intensity": intensity,
        "duration_minutes": dur,
        "why": why,
    }
    if zone_target:
        result["zone_target"] = zone_target
    return result


# ---------------------------------------------------------------------------
# 8. compute_trends
# ---------------------------------------------------------------------------

def compute_trends(
    training_status: dict,
    hrv: dict,
    sleep: dict,
    daily_records: list[dict],
) -> dict:
    """Aggregate fitness, fatigue, HRV, and sleep trends."""
    stamina_trend = training_status.get("intensity_trend", "Stable")

    fatigue_vals = [r.get("tired_rate") for r in daily_records[:14]
                    if r.get("tired_rate") is not None]
    recent_fatigue = _avg(fatigue_vals[:3]) if fatigue_vals else None
    previous_fatigue = _avg(fatigue_vals[3:7]) if len(fatigue_vals) > 3 else None
    fatigue_trend = "Falling" if (recent_fatigue is not None and previous_fatigue is not None
                                   and recent_fatigue < previous_fatigue) else \
                    "Rising" if (recent_fatigue is not None and previous_fatigue is not None
                                  and recent_fatigue > previous_fatigue) else "Stable"

    return {
        "fitness": stamina_trend,
        "fatigue": fatigue_trend,
        "hrv": hrv.get("trend", "Stable"),
        "sleep": sleep.get("trend", "Stable"),
    }


# ---------------------------------------------------------------------------
# 9. generate_alerts
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

    # 1. HRV below baseline for N+ consecutive days
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
            alerts.append(f"HRV below baseline for {streak} consecutive days — nervous system may be under-recovered")

    # 2. Sleep debt > threshold
    if sleep_records and sleep_records[:3]:
        recent_dur = _avg([r.get("total_duration_minutes") for r in sleep_records[:3]])
        if recent_dur is not None:
            debt_hours = (SLEEP_OPTIMAL_MINUTES - recent_dur) / 60
            if debt_hours >= SLEEP_DEBT_ALERT_HOURS:
                alerts.append(f"Sleep debt of {debt_hours:.1f}h over last 3 nights — prioritize sleep")

    # 3. High training load ratio for 3+ days
    high_load_streak = 0
    for r in daily_records[:7]:
        if r.get("training_load_ratio_state") == 3:
            high_load_streak += 1
        else:
            break
    if high_load_streak >= 3:
        alerts.append(f"Training load ratio in 'High' zone for {high_load_streak} consecutive days — consider deload")

    # 4. Inactivity
    training_days = [r for r in daily_records if r.get("training_load") and r.get("training_load", 0) > 0]
    if len(daily_records) >= INACTIVITY_DAYS and not training_days:
        total_days = len([r for r in daily_records if r.get("date")])
        if total_days >= INACTIVITY_DAYS:
            alerts.append(f"No training recorded in {total_days}+ days — may be losing fitness")

    # 5. RHR elevated
    rhrs = [(r.get("rhr"), r.get("date")) for r in daily_records if r.get("rhr") is not None]
    if len(rhrs) >= 2:
        latest_rhr = rhrs[0][0]
        week_avg = _avg([h for h, _ in rhrs[1:7]])
        if week_avg is not None and latest_rhr > week_avg + RHR_ELEVATED_ALERT_BPM:
            alerts.append(f"RHR elevated {latest_rhr - week_avg:.0f} bpm above 7-day avg — possible overtraining or illness")

    # 6. Overtrained fatigue
    if fatigue.get("level") == "Overtrained":
        alerts.append("Fatigue assessment: Overtrained — extended rest recommended")

    return alerts


# ---------------------------------------------------------------------------
# 10. determine_overall_status
# ---------------------------------------------------------------------------

def determine_overall_status(readiness: dict, fatigue: dict, training_status: dict) -> str:
    """Map readiness × fatigue × training_status to a final status label."""
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


# ---------------------------------------------------------------------------
# Main compose function
# ---------------------------------------------------------------------------

def build_coach_briefing(
    daily_records: list[dict],
    sleep_records: list[dict] | None = None,
    schedule: list[dict] | None = None,
    daily_health: list[dict] | None = None,
    user_profile: dict | None = None,
    dashboard: dict | None = None,
) -> dict:
    """Compose the full coaching briefing from all available Coros data.

    All parameters are plain dicts (already deserialized from JSON).
    No I/O, no randomness — deterministic output.
    """
    sleep_records = sleep_records or []
    schedule = schedule or []
    daily_health = daily_health or []
    user_profile = user_profile or {}
    dashboard = dashboard or {}

    recovery_hours = None
    summary = dashboard.get("summaryInfo", {})
    if isinstance(summary, dict):
        raw = summary.get("fullRecoveryHours")
        if raw is not None:
            try:
                recovery_hours = int(raw)
            except (TypeError, ValueError):
                pass

    evo_lab_ready = True
    sport = dashboard.get("sportDataSummary", {})
    if isinstance(sport, dict):
        evo_lab_ready = sport.get("modelValidState", True) is True

    readiness = assess_readiness(daily_records, sleep_records, user_profile, recovery_hours)
    fatigue = assess_fatigue(daily_records, sleep_records, daily_health)
    training_status = compute_training_status(daily_records)
    hrv = analyze_hrv_trend(daily_records)
    sleep = analyze_sleep_trend(sleep_records)
    recommendation = generate_recommendation(readiness, fatigue, training_status, schedule, user_profile)
    weekly_summary = compute_weekly_comparison(daily_records)
    trends = compute_trends(training_status, hrv, sleep, daily_records)
    alerts = generate_alerts(daily_records, sleep_records, training_status, hrv, fatigue)
    overall = determine_overall_status(readiness, fatigue, training_status)

    result = {
        "overall_status": overall,
        "readiness": readiness,
        "fatigue": fatigue,
        "training_status": training_status,
        "hrv": hrv,
        "sleep": sleep,
        "today_recommendation": recommendation,
        "weekly_summary": weekly_summary,
        "trends": trends,
        "alerts": alerts,
    }
    if not evo_lab_ready:
        result["evo_lab_ready"] = False
    return result
