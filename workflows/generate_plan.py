"""Generate a weekly training plan — fixed logic, no AI decisions.

Flow:
1. Fetch current training state
2. Get Coros weekly TL recommendation
3. Apply safety caps
4. Distribute load across days (template)
5. Match workouts from library (best-effort)
6. Safety check
7. Return plan for review (no auto-scheduling)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

# Day-to-type default template (phase-specific overrides in PHASE_TEMPLATES)
DEFAULT_WEEK = {
    0: ("recovery", 0.15),  # Monday
    1: ("easy",     0.25),  # Tuesday
    2: ("quality",  0.30),  # Wednesday
    3: ("easy",     0.15),  # Thursday
    4: ("rest",     0.00),  # Friday
    5: ("long",     0.35),  # Saturday
    6: ("recovery", 0.10),  # Sunday
}

PHASE_TEMPLATES = {
    "base": {
        0: ("recovery", 0.10), 1: ("easy", 0.25), 2: ("quality", 0.25),
        3: ("easy", 0.15), 4: ("rest", 0), 5: ("long", 0.35), 6: ("recovery", 0.10),
    },
    "build": {
        0: ("recovery", 0.10), 1: ("easy", 0.20), 2: ("quality", 0.30),
        3: ("easy", 0.15), 4: ("rest", 0), 5: ("long", 0.30), 6: ("recovery", 0.10),
    },
    "peak": {
        0: ("rest", 0), 1: ("quality", 0.25), 2: ("easy", 0.20),
        3: ("quality", 0.30), 4: ("rest", 0), 5: ("long", 0.25), 6: ("recovery", 0.10),
    },
    "taper": {
        0: ("rest", 0), 1: ("easy", 0.30), 2: ("quality", 0.20),
        3: ("rest", 0), 4: ("easy", 0.15), 5: ("long", 0.20), 6: ("rest", 0),
    },
}

# Safety limits
MAX_LOAD_RATIO = 1.3
MAX_CONSECUTIVE_HARD = 2  # quality + long count as "hard"
MIN_EASY_AFTER_HARD = 1


async def run(auth, start_day: str, phase: str = "base") -> dict:
    """Generate a week-long training plan.

    Parameters
    ----------
    auth : StoredAuth
    start_day : str — Monday date in YYYYMMDD (e.g., "20260601")
    phase : str — "base" | "build" | "peak" | "taper"

    Returns
    -------
    dict with: week_start, phase, weekly_tl_target, daily_plan,
    safety_checks, projection (if available)
    """
    from coros_api import (
        fetch_training_analysis, fetch_training_library,
        fetch_schedule, fetch_activities,
    )

    # ── Step 1: Fetch current state ──
    today = datetime.now().strftime("%Y%m%d")
    analysis = await fetch_training_analysis(auth, today, today)
    daily = analysis.get("daily_records", [])

    # Current load metrics
    current_cti = daily[0].get("training_load_ratio_state", 2) if daily else 2
    current_ratio = daily[0].get("training_load_ratio", 0.8) if daily else 0.8

    # ── Step 2: Get Coros weekly TL recommendation ──
    week_list = analysis.get("week_list", [])
    tl_min = tl_max = None
    if week_list:
        latest_week = week_list[0]
        tl_min = latest_week.get("recomend_tl_min")
        tl_max = latest_week.get("recomend_tl_max")

    # Fallback
    if tl_max is None:
        tl_max = 500
    if tl_min is None:
        tl_min = 350

    # ── Step 3: Apply safety caps ──
    if current_ratio >= MAX_LOAD_RATIO:
        tl_max = min(tl_max, current_cti * 0.8 if daily else 300)
    weekly_tl_target = min(tl_max, max(tl_min, int((tl_min + tl_max) / 2)))

    # ── Step 4: Distribute load across days ──
    template = PHASE_TEMPLATES.get(phase, DEFAULT_WEEK)
    start_date = datetime.strptime(start_day, "%Y%m%d")

    daily_plan = []
    consecutive_hard = 0

    for dow in range(7):
        day_type, fraction = template.get(dow, ("easy", 0.10))
        day_date = (start_date + timedelta(days=dow)).strftime("%Y%m%d")
        day_tl = int(weekly_tl_target * fraction) if day_type != "rest" else 0

        # Safety: cap consecutive hard days
        if day_type in ("quality", "long"):
            consecutive_hard += 1
        else:
            consecutive_hard = 0

        if consecutive_hard > MAX_CONSECUTIVE_HARD:
            day_type = "easy"
            day_tl = int(weekly_tl_target * 0.15)
            consecutive_hard = 0

        daily_plan.append({
            "date": day_date,
            "dow": dow + 1,
            "type": day_type,
            "target_tl": day_tl,
        })

    # ── Step 5: Match workouts from library (best-effort) ──
    try:
        catalog = await fetch_training_library("cn", "zh-CN", category="workout", sport_type="run")
    except Exception:
        catalog = []

    workouts_by_tl = sorted(catalog, key=lambda w: abs(
        (getattr(w, "estimated_training_load", None) or 50) - 100
    ))

    for day in daily_plan:
        if day["target_tl"] == 0:
            day["workout_name"] = "休息"
            continue
        # Simple matching: find workout nearest to target TL
        best = None
        best_diff = float("inf")
        for w in workouts_by_tl:
            w_tl = getattr(w, "estimated_training_load", None)
            if w_tl is None:
                continue
            # Filter by type
            if day["type"] == "recovery" and w_tl > 80:
                continue
            if day["type"] == "long" and w_tl < 120:
                continue
            diff = abs(w_tl - day["target_tl"])
            if diff < best_diff:
                best_diff = diff
                best = w
        if best:
            day["workout_name"] = best.title
            day["workout_tl"] = getattr(best, "estimated_training_load", None)
            day["linked_id"] = best.linked_id
        else:
            day["workout_name"] = "手动安排"
            day["workout_tl"] = day["target_tl"]

    # ── Step 6: Safety check ──
    safety_checks = []
    total_planned_tl = sum(d.get("workout_tl", 0) or 0 for d in daily_plan)
    hard_days = [d for d in daily_plan if d["type"] in ("quality", "long")]
    if len(hard_days) > 3:
        safety_checks.append("高强度日超过 3 天")
    if total_planned_tl > weekly_tl_target * 1.2:
        safety_checks.append(f"计划 TL({total_planned_tl})超目标({weekly_tl_target})20%")
    for i in range(len(hard_days) - 2):
        if (hard_days[i + 1]["dow"] - hard_days[i]["dow"] == 1 and
                hard_days[i + 2]["dow"] - hard_days[i + 1]["dow"] == 1):
            safety_checks.append("连续 3 天高强度")

    # ── Step 7: Return plan ──
    return {
        "week_start": start_day,
        "phase": phase,
        "current_load_ratio": current_ratio,
        "coros_recommended_tl": {"min": tl_min, "max": tl_max},
        "weekly_tl_target": weekly_tl_target,
        "total_planned_tl": total_planned_tl,
        "daily_plan": daily_plan,
        "safety_checks": safety_checks,
        "status": "review" if safety_checks else "ready",
    }
