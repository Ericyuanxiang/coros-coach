"""Training analysis — status, weekly comparison, trends, plan projection."""

from datetime import datetime

from . import _avg, _trend, _trend_detail, _format_pace, _confidence
from .thresholds import (
    STAMINA_TREND_PCT,
    TREND_PCT,
    PLAN_LOAD_RATIO_SAFE,
    PLAN_LOAD_RATIO_EFFICIENT,
    PLAN_LOAD_RATIO_WARNING,
    PLAN_LOAD_RATIO_DANGER,
    PLAN_WEEKLY_LOAD_JUMP_PCT,
    PLAN_CTI_FALLING_DAYS,
)


# ---------------------------------------------------------------------------
# 1. Training Status (EvoLab CSB model)
# ---------------------------------------------------------------------------

def compute_training_status(daily_records: list[dict]) -> dict:
    """Determine training status using Coros EvoLab data (CSB model).

    Uses training_load_ratio_state (1=Low, 2=Optimal, 3=High) and stamina trend.
    Returns dict with: state, base_fitness, load_impact, intensity_trend,
    training_load_ratio.
    """
    if not daily_records:
        return {"state": "Insufficient Data", "base_fitness": None,
                "load_impact": None, "intensity_trend": "Stable",
                "training_load_ratio": None}

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
# 2. Weekly Comparison
# ---------------------------------------------------------------------------

def compute_weekly_comparison(daily_records: list[dict]) -> dict:
    """Compare this week (last 7 days) to last week (days 7-13).

    Returns dict with: this_week_load, last_week_load, load_change_pct,
    total_duration_hours, total_distance_km, sessions_completed.
    """
    this_week = daily_records[:7]
    last_week = daily_records[7:14]

    def sum_week(records):
        loads = [r.get("training_load") for r in records
                 if r.get("training_load")]
        durations = [r.get("duration") for r in records if r.get("duration")]
        distances = [r.get("distance") for r in records if r.get("distance")]
        sessions = len([r for r in records
                        if r.get("training_load") or r.get("duration")])
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
# 3. Trends
# ---------------------------------------------------------------------------

def compute_trends(
    training_status: dict,
    hrv: dict,
    sleep: dict,
    daily_records: list[dict],
) -> dict:
    """Aggregate fitness, fatigue, HRV, and sleep trends with detail and confidence.

    Each trend returns {direction, delta_pct, detail, confidence}.
    """
    # Fitness trend (from training_status)
    intensity_trend = training_status.get("intensity_trend", "Stable")
    stamina_vals = [r.get("stamina_level") for r in daily_records[:14]
                    if r.get("stamina_level") is not None]
    recent_stamina = _avg(stamina_vals[:3]) if stamina_vals else None
    previous_stamina = (_avg(stamina_vals[3:7])
                        if len(stamina_vals) > 3 else None)
    delta_pct = None
    if (recent_stamina is not None and previous_stamina is not None
            and previous_stamina != 0):
        delta_pct = round(
            (recent_stamina - previous_stamina) / previous_stamina * 100, 1)
    stamina_detail = {
        "direction": intensity_trend,
        "delta_pct": delta_pct,
        "detail": (
            f"Stamina: {recent_stamina:.1f}" if recent_stamina is not None
            else "Stamina: N/A"
        ),
        "confidence": _confidence(len(stamina_vals)),
    }

    # Fatigue trend (from tired_rate)
    fatigue_vals = [r.get("tired_rate") for r in daily_records[:14]
                    if r.get("tired_rate") is not None]
    recent_fatigue = _avg(fatigue_vals[:3]) if fatigue_vals else None
    previous_fatigue = (_avg(fatigue_vals[3:7])
                        if len(fatigue_vals) > 3 else None)
    fatigue_detail = _trend_detail(recent_fatigue, previous_fatigue, TREND_PCT)
    if fatigue_detail["direction"] == "Rising":
        fatigue_detail["direction"] = "Rising (worse)"
    elif fatigue_detail["direction"] == "Falling":
        fatigue_detail["direction"] = "Falling (improving)"
    fatigue_detail["detail"] = (
        f"tired_rate: {recent_fatigue:.0f}" if recent_fatigue is not None
        else "tired_rate: N/A"
    )
    fatigue_detail["confidence"] = _confidence(len(fatigue_vals))

    # HRV trend (from HRV analysis)
    hrv_vals = [(r.get("avg_sleep_hrv"), r.get("date"))
                for r in daily_records if r.get("avg_sleep_hrv") is not None]
    recent_hrv = _avg([h for h, _ in hrv_vals[:3]]) if hrv_vals else None
    previous_hrv = (_avg([h for h, _ in hrv_vals[3:7]])
                    if len(hrv_vals) > 3 else None)
    hrv_detail = _trend_detail(recent_hrv, previous_hrv, 3.0)
    hrv_detail["detail"] = (
        f"HRV 7d avg: {hrv.get('seven_day_avg')}ms, "
        f"deviation: {hrv.get('deviation_pct')}%"
    )
    hrv_detail["confidence"] = _confidence(len(hrv_vals))

    # Sleep trend
    sleep_trend = sleep.get("trend", "Stable")
    sleep_detail = {
        "direction": sleep_trend,
        "delta_pct": None,
        "detail": (f"Sleep avg: {sleep.get('avg_duration_hours')}h, "
                   f"debt: {sleep.get('debt_hours')}h"),
        "confidence": "medium",
    }

    return {
        "fitness": stamina_detail,
        "fatigue": fatigue_detail,
        "hrv": hrv_detail,
        "sleep": sleep_detail,
    }


# ---------------------------------------------------------------------------
# 4. Recent Training Summary
# ---------------------------------------------------------------------------

def summarize_recent_training(activities: list[dict] | None = None) -> dict:
    """Extract structured training history from activity summaries.

    Returns dict with: sessions (list), by_sport (grouped stats),
    total_sessions, total_duration_min, total_distance_km, total_training_load.
    """
    activities = activities or []
    sessions = []
    sport_groups: dict[str, dict] = {}

    for a in activities:
        duration_sec = a.get("duration_seconds") or 0
        distance_m = a.get("distance_meters") or 0
        sport = a.get("sport_name") or "Unknown"
        date = (a.get("start_time") or "")[:8]

        session = {
            "date": date,
            "sport": sport,
            "name": a.get("name"),
            "duration_min": (round(duration_sec / 60, 0)
                             if duration_sec else 0),
            "distance_km": (round(distance_m / 1000, 2)
                            if distance_m else 0),
            "avg_hr": a.get("avg_hr"),
            "max_hr": a.get("max_hr"),
            "training_load": a.get("training_load"),
            "elevation_gain_m": a.get("elevation_gain"),
            "avg_pace": _format_pace(a.get("avg_pace")),
        }
        sessions.append(session)

        if sport not in sport_groups:
            sport_groups[sport] = {"sessions": 0, "duration_min": 0,
                                   "distance_km": 0, "training_load": 0}
        g = sport_groups[sport]
        g["sessions"] += 1
        g["duration_min"] += session["duration_min"]
        g["distance_km"] += session["distance_km"]
        g["training_load"] += session["training_load"] or 0

    return {
        "sessions": sessions,
        "by_sport": sport_groups,
        "total_sessions": len(sessions),
        "total_duration_min": round(sum(s["duration_min"] for s in sessions), 0),
        "total_distance_km": round(sum(s["distance_km"] for s in sessions), 2),
        "total_training_load": sum(s["training_load"] or 0 for s in sessions),
    }


# ---------------------------------------------------------------------------
# 5. Data Freshness
# ---------------------------------------------------------------------------

def build_data_freshness(
    daily_records: list[dict],
    sleep_records: list[dict],
    activities: list[dict] | None = None,
    _now: str | None = None,
) -> dict:
    """Report how fresh each data source is.

    Pass _now as "YYYYMMDD" for deterministic testing.
    """
    if _now:
        now_dt = datetime.strptime(_now, "%Y%m%d")
    else:
        now_dt = datetime.now()

    activities = activities or []

    training_dates = sorted(
        [r.get("date") for r in daily_records
         if (r.get("training_load") or 0) > 0],
        reverse=True,
    )
    for a in activities:
        d = a.get("start_time", "")[:8]
        if d:
            training_dates.append(d)
    training_dates = sorted(set(training_dates), reverse=True)

    hrv_dates = sorted(
        [r.get("date") for r in daily_records
         if r.get("avg_sleep_hrv") is not None],
        reverse=True,
    )
    sleep_dates = sorted(
        [r.get("date") for r in sleep_records],
        reverse=True,
    )
    all_dates = [r.get("date") for r in daily_records if r.get("date")]
    start = min(all_dates) if all_dates else None
    end = max(all_dates) if all_dates else None

    def _days_since(date_str: str | None) -> int | None:
        if not date_str:
            return None
        try:
            delta = now_dt - datetime.strptime(date_str, "%Y%m%d")
            return delta.days
        except ValueError:
            return None

    last_training = training_dates[0] if training_dates else None
    last_hrv = hrv_dates[0] if hrv_dates else None
    last_sleep = sleep_dates[0] if sleep_dates else None

    days_training = _days_since(last_training)
    days_hrv = _days_since(last_hrv)
    days_sleep = _days_since(last_sleep)

    gap_messages = []
    if days_training and days_training > 5:
        gap_messages.append(
            f"no training recorded since {last_training} ({days_training} days)")
    if days_hrv and days_hrv > 2:
        gap_messages.append(
            f"HRV data missing since {last_hrv} ({days_hrv} days)")
    if days_sleep and days_sleep > 2:
        gap_messages.append(
            f"sleep data missing since {last_sleep} ({days_sleep} days)")

    return {
        "generated_at": now_dt.isoformat(),
        "data_window": {
            "start": start,
            "end": end,
            "days": len(all_dates) if all_dates else 0,
        },
        "last_training_date": last_training,
        "days_since_training": days_training,
        "last_hrv_date": last_hrv,
        "days_since_hrv": days_hrv,
        "last_sleep_date": last_sleep,
        "days_since_sleep": days_sleep,
        "gaps": gap_messages,
    }


# ---------------------------------------------------------------------------
# 6. Plan Projection Analysis (NEW)
# ---------------------------------------------------------------------------

def _classify_load_ratio(ratio: float) -> dict:
    """Classify a training load ratio into risk zone."""
    if ratio < PLAN_LOAD_RATIO_SAFE:
        return {"zone": "safe", "label": "安全区",
                "risk": "low",
                "detail": "负荷比 < 0.8，训练刺激偏保守，适合恢复/适应期"}
    if ratio <= PLAN_LOAD_RATIO_EFFICIENT:
        return {"zone": "efficient", "label": "高效区",
                "risk": "low",
                "detail": "负荷比 0.8-1.0，训练与恢复平衡，可持续积累"}
    if ratio <= PLAN_LOAD_RATIO_WARNING:
        return {"zone": "efficient_upper", "label": "高效区上沿",
                "risk": "medium",
                "detail": "负荷比 1.0-1.3，短期负荷推动适应，需关注恢复"}
    if ratio < PLAN_LOAD_RATIO_DANGER:
        return {"zone": "warning", "label": "警戒区",
                "risk": "high",
                "detail": "负荷比 1.3-1.5，接近安全上限，建议减量或插入恢复日"}
    return {"zone": "danger", "label": "危险区",
            "risk": "critical",
            "detail": "负荷比 > 1.5，受伤风险 RR 2.0-4.0 (Gabbett 2016)"}


def analyze_plan_projection(week_data: list[dict]) -> dict:
    """Analyze multi-week plan projection from COROS training summary data.

    Args:
        week_data: List of week-level dicts, each from get_training_summary.
                   Each dict should have: firstDayInWeek, weekTrainSum
                   (with planAti, planCti, planTrainingLoadRatio, planTrainingLoad,
                   actualAti, actualCti, actualTrainingLoadRatio).

    Returns:
        dict with: weeks (list of per-week analysis), overall_assessment,
        ctTrajectory, load_ratio_curve, warnings.
    """
    if not week_data:
        return {"weeks": [], "overall_assessment": "No plan data available",
                "cti_trajectory": None, "load_ratio_curve": [],
                "warnings": ["No plan data — cannot analyze"]}

    weeks = []
    cti_values: list[dict] = []
    ratio_curve: list[dict] = []
    warnings: list[dict] = []
    prev_load = None
    prev_cti = None

    for w in week_data:
        ws = w.get("weekTrainSum", {})
        first_day = w.get("firstDayInWeek")

        plan_ati = ws.get("planAti")
        plan_cti = ws.get("planCti")
        plan_ratio = ws.get("planTrainingLoadRatio")
        plan_load = ws.get("planTrainingLoad", 0)
        actual_ati = ws.get("actualAti")
        actual_cti = ws.get("actualCti")
        actual_ratio = ws.get("actualTrainingLoadRatio")

        ratio_class = None
        if plan_ratio is not None:
            ratio_class = _classify_load_ratio(plan_ratio)

        week_entry = {
            "start_date": str(first_day) if first_day else None,
            "plan": {
                "training_load": plan_load,
                "ati": plan_ati,
                "cti": plan_cti,
                "ratio": plan_ratio,
            },
            "actual": {
                "ati": actual_ati,
                "cti": actual_cti,
                "ratio": actual_ratio,
            },
            "ratio_risk": ratio_class,
        }
        weeks.append(week_entry)

        if plan_cti is not None:
            cti_values.append({"week_start": str(first_day)
                               if first_day else None,
                               "plan_cti": plan_cti,
                               "actual_cti": actual_cti})

        if plan_ratio is not None and first_day:
            ratio_curve.append({"week_start": str(first_day),
                                "ratio": plan_ratio,
                                "zone": (ratio_class["zone"]
                                         if ratio_class else "unknown")})

        # Warning: CTI falling
        if prev_cti is not None and plan_cti is not None:
            if plan_cti < prev_cti:
                warnings.append({
                    "type": "cti_falling",
                    "severity": "warning",
                    "detail": (f"Week {first_day}: CTI {prev_cti}→{plan_cti} "
                               "still declining — training load may be "
                               "insufficient to maintain base fitness"),
                })
        if plan_cti is not None:
            prev_cti = plan_cti

        # Warning: Weekly load jump > 30%
        if prev_load is not None and prev_load > 0 and plan_load > 0:
            jump_pct = ((plan_load - prev_load) / prev_load) * 100
            if jump_pct > PLAN_WEEKLY_LOAD_JUMP_PCT:
                warnings.append({
                    "type": "load_jump",
                    "severity": "warning",
                    "detail": (f"Week {first_day}: training load "
                               f"{prev_load}→{plan_load} "
                               f"(+{jump_pct:.0f}%) — exceeds "
                               f"{PLAN_WEEKLY_LOAD_JUMP_PCT}% safe threshold "
                               "(Cloosterman et al. 2024)"),
                })
        prev_load = plan_load

        # Warning: Ratio danger zone
        if plan_ratio is not None and plan_ratio >= PLAN_LOAD_RATIO_DANGER:
            warnings.append({
                "type": "ratio_danger",
                "severity": "critical",
                "detail": (f"Week {first_day}: load ratio {plan_ratio:.2f} "
                           f"≥ {PLAN_LOAD_RATIO_DANGER} — injury risk RR 2.0-4.0 "
                           "(Gabbett 2016). Force deload week."),
            })
        elif plan_ratio is not None and plan_ratio >= PLAN_LOAD_RATIO_WARNING:
            warnings.append({
                "type": "ratio_warning",
                "severity": "caution",
                "detail": (f"Week {first_day}: load ratio {plan_ratio:.2f} "
                           f"approaching limit ({PLAN_LOAD_RATIO_WARNING}). "
                           "Monitor recovery closely."),
            })

    # CTI trajectory assessment
    cti_trajectory = None
    if len(cti_values) >= 2:
        cti_start = cti_values[0]["plan_cti"]
        cti_end = cti_values[-1]["plan_cti"]
        if cti_start is not None and cti_end is not None:
            change = cti_end - cti_start
            if change > 3:
                direction = "rising"
            elif change < -3:
                direction = "falling"
            else:
                direction = "stable"

            # Find turnaround week (where CTI stopped falling)
            turnaround = None
            for i in range(1, len(cti_values)):
                prev = cti_values[i - 1].get("plan_cti")
                curr = cti_values[i].get("plan_cti")
                if (prev is not None and curr is not None
                        and prev < curr and direction in ("rising", "stable")):
                    turnaround = cti_values[i]["week_start"]
                    break

            cti_trajectory = {
                "direction": direction,
                "start": cti_start,
                "end": cti_end,
                "change": change,
                "turnaround_week": turnaround,
            }

    # Overall assessment
    critical_count = sum(1 for w in warnings
                         if w["severity"] == "critical")
    warning_count = sum(1 for w in warnings
                        if w["severity"] in ("warning", "caution"))
    max_ratio = max((w["plan"]["ratio"] for w in weeks
                     if w["plan"]["ratio"] is not None), default=0)

    if critical_count > 0:
        overall = (f"Plan has {critical_count} critical issue(s) — "
                   f"must adjust before execution")
    elif max_ratio < PLAN_LOAD_RATIO_SAFE:
        overall = "Conservative plan — all weeks in safe zone. Good for return-to-training."
    elif max_ratio <= PLAN_LOAD_RATIO_WARNING:
        overall = (f"Progressive plan — peak ratio {max_ratio:.2f} within safe "
                   f"bounds. Monitor W3-W4 recovery.")
    else:
        overall = (f"Plan approaches upper limit — peak ratio {max_ratio:.2f}. "
                   f"Ensure deload week follows within 4 weeks.")

    return {
        "weeks": weeks,
        "overall_assessment": overall,
        "cti_trajectory": cti_trajectory,
        "load_ratio_curve": ratio_curve,
        "warnings": warnings,
    }
