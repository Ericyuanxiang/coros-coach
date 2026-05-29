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

import asyncio
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


def _ai_workout_prompt(day_type: str, target_tl: int) -> dict:
    """Return a structured prompt for AI to create a custom workout."""
    prompts = {
        "recovery": {
            "description": f"恢复跑，目标 TL≈{target_tl}",
            "guide": "Z1-Z2 低强度，30-45 分钟，心率不超过 Z2",
        },
        "easy": {
            "description": f"轻松有氧跑，目标 TL≈{target_tl}",
            "guide": "Z2 中等强度，45-75 分钟，心率保持在有氧区",
        },
        "quality": {
            "description": f"质量训练，目标 TL≈{target_tl}",
            "guide": "间歇或节奏跑，包含热身+主课+放松。主课可用 400m/800m/1km 重复或 Z3-Z5 连续跑",
        },
        "long": {
            "description": f"长距离跑，目标 TL≈{target_tl}",
            "guide": "Z2 配速，60-150 分钟，目标是有氧耐力积累",
        },
    }
    p = prompts.get(day_type, prompts["easy"])
    return {
        "type": day_type,
        "target_training_load": target_tl,
        "task": f"使用 create_workout 创建一个跑步训练: {p['description']}。{p['guide']}。",
    }


async def run(auth, start_day: str, phase: str = "base",
             auto_schedule: bool = False) -> dict:
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

    # Current load + fatigue metrics
    latest = daily[0] if daily else {}
    current_ratio = latest.get("training_load_ratio", 0.8)
    current_ati = latest.get("ati", 0)
    current_cti_val = latest.get("cti", 50)
    current_tired_rate = latest.get("tired_rate", 0)
    current_fatigue_state = latest.get("tired_rate_state_new", 2)

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
        tl_max = min(tl_max, int(current_cti_val * 0.8))
    if current_fatigue_state == 3:  # overtrained → force deload
        tl_max = min(tl_max, 300)
        tl_min = min(tl_min, 200)
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

    # ── Step 5: Match workouts from library ──
    # Import a diverse pool of workouts, calculate their TL, then match
    from coros_api import import_training_program, fetch_program_calculate, _fetch_raw_workout

    try:
        catalog = await fetch_training_library("cn", "zh-CN", category="workout", sport_type="run")
    except Exception:
        catalog = []

    # Pick diverse candidates (different difficulty levels)
    pool: list[str] = []
    seen_difficulty: set[str] = set()
    for w in catalog:
        diff = w.difficulties[0] if w.difficulties else "any"
        if len(pool) >= 12:
            break
        if diff not in seen_difficulty or len(pool) < 6:
            pool.append(w.linked_id)
            seen_difficulty.add(diff)

    # Import + calculate TL in parallel
    imported: dict[str, dict] = {}

    async def _import_and_calc(linked_id: str, title: str):
        try:
            result = await import_training_program(auth, linked_id, "workout", 1, title)
            wid = result["imported_id"]
            raw = await _fetch_raw_workout(auth, wid)
            est = await fetch_program_calculate(auth, raw)
            return {
                "linked_id": linked_id,
                "id": wid,
                "title": title,
                "tl": est.get("planTrainingLoad", 50),
                "duration_s": est.get("planDuration", 3600),
            }
        except Exception:
            return None

    tasks = []
    for w in catalog:
        if w.linked_id in pool:
            tasks.append(_import_and_calc(w.linked_id, w.title))
    results = await asyncio.gather(*tasks)

    for r in results:
        if r:
            imported[r["linked_id"]] = r

    # Type-priority keywords for workout matching
    TYPE_KEYWORDS = {
        "recovery": ("恢复", "基础训练", "轻松"),
        "easy":     ("基础训练", "MAF", "轻松跑"),
        "quality":  ("间歇", "VO2max", "节奏", "金字塔", "速度"),
        "long":     ("LSD", "长距离", "耐力"),
    }

    # Match each day to the best workout in our imported pool
    for day in daily_plan:
        if day["target_tl"] == 0:
            day["workout_name"] = "休息"
            continue

        keywords = TYPE_KEYWORDS.get(day["type"], ())
        best = None
        best_score = float("inf")

        for wid, w in imported.items():
            tl = w["tl"]
            title = w["title"]

            # Hard filters
            if day["type"] == "recovery" and tl > 70:
                continue
            if day["type"] == "long" and tl < 100:
                continue
            if day["type"] == "quality" and tl < 80:
                continue
            if day["type"] == "easy" and tl > 120:
                continue

            # Score: TL mismatch (primary) + type penalty
            tl_diff = abs(tl - day["target_tl"])
            type_match = any(kw in title for kw in keywords)
            type_penalty = 0 if type_match else 60  # prefer type-matched workouts
            score = tl_diff + type_penalty

            if score < best_score:
                best_score = score
                best = w
        if best:
            day["workout_name"] = best["title"]
            day["workout_tl"] = best["tl"]
            day["linked_id"] = best["linked_id"]
            day["imported_id"] = best["id"]
        else:
            # No library match — ask AI to create one
            day["workout_name"] = None
            day["workout_tl"] = day["target_tl"]
            day["ai_workout"] = _ai_workout_prompt(day["type"], day["target_tl"])

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

    # ── Step 7: Optionally schedule + verify projection ──
    projection = None
    if auto_schedule:
        from coros_api import schedule_workout
        for day in daily_plan:
            if day.get("imported_id") and day["target_tl"] > 0:
                try:
                    await schedule_workout(auth, day["imported_id"], day["date"], 1)
                    day["scheduled"] = True
                except Exception:
                    day["scheduled"] = False

        # Fetch weekly projection
        try:
            end_day = (start_date + timedelta(days=6)).strftime("%Y%m%d")
            sched = await fetch_schedule(auth, start_day, end_day)
            weeks = sched.get("weekStages", [])
            if weeks:
                ws = weeks[0].get("trainSum", {})
                projection = {
                    "long_term_load": ws.get("actualCti"),
                    "short_term_load": ws.get("actualAti"),
                    "load_ratio": round((ws.get("actualTrainingLoadRatio") or 0) * 100),
                    "plan_time": f"{ws.get('planDuration', 0) // 3600}h{(ws.get('planDuration', 0) % 3600) // 60}m",
                    "plan_training_load": ws.get("planTrainingLoad"),
                }
        except Exception:
            pass

    # ── Step 8: Return plan ──
    return {
        "week_start": start_day,
        "phase": phase,
        "current_state": {
            "load_ratio": current_ratio,
            "ati": current_ati,
            "cti": current_cti_val,
            "tired_rate": current_tired_rate,
            "fatigue_state": current_fatigue_state,
        },
        "coros_recommended_tl": {"min": tl_min, "max": tl_max},
        "weekly_tl_target": weekly_tl_target,
        "total_planned_tl": total_planned_tl,
        "daily_plan": daily_plan,
        "safety_checks": safety_checks,
        "projection": projection,
        "status": "review" if safety_checks else "ready",
    }
