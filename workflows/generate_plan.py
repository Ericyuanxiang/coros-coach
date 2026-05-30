"""Generate a weekly training plan — AI embedded in the workflow.

Two-phase: Phase 1 builds framework → AI fills decisions → Phase 2 validates + schedules.

Usage:
  framework = await run(auth, "20260601", "build")
  # AI fills weekly_tl + workout_picks
  plan = await run(auth, "20260601", "build", ai_decision={...})
"""

import asyncio
from datetime import datetime, timedelta

# Day-to-type default template
DEFAULT_WEEK = {
    0: ("recovery", 0.15), 1: ("easy", 0.25), 2: ("quality", 0.30),
    3: ("easy", 0.15), 4: ("rest", 0.00), 5: ("long", 0.35), 6: ("recovery", 0.10),
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

LOAD_RATIO_DANGER = 1.5
LOAD_RATIO_WARNING = 1.3
MAX_CONSECUTIVE_HARD = 2


async def run(auth, start_day: str, phase: str = "base",
              ai_decision: dict | None = None) -> dict:
    """Generate a weekly training plan.

    Phase 1 (ai_decision=None): return framework for AI to fill
    Phase 2 (ai_decision provided): validate, schedule, verify
    """
    from coros_api import (
        fetch_training_analysis, fetch_training_library,
        fetch_schedule,
        import_training_program, fetch_program_calculate, _fetch_raw_workout,
    )

    # ═══════════════════════════════════════════════
    # Phase 1: Build framework
    # ═══════════════════════════════════════════════

    # Step 1: Fetch current state
    today = datetime.now().strftime("%Y%m%d")
    analysis = await fetch_training_analysis(auth, today, today)
    daily = analysis.get("daily_records", [])

    latest = daily[0] if daily else {}
    current_ratio = latest.get("training_load_ratio", 0.8)
    current_ati = latest.get("ati", 0)
    current_cti_val = latest.get("cti", 50)
    current_tired_rate = latest.get("tired_rate", 0)
    current_fatigue_state = latest.get("tired_rate_state_new", 2)

    # Step 2: Coros TL recommendation
    week_list = analysis.get("week_list", [])
    tl_min, tl_max = 350, 500
    if week_list:
        w = week_list[0]
        if w.get("recomend_tl_min") is not None:
            tl_min = w["recomend_tl_min"]
        if w.get("recomend_tl_max") is not None:
            tl_max = w["recomend_tl_max"]

    # Step 3: Safety caps (only danger zone — 1.5 is hard limit)
    if current_ratio >= LOAD_RATIO_DANGER:
        tl_max = min(tl_max, int(current_cti_val * 0.8))
    if current_fatigue_state == 3:
        tl_max = min(tl_max, 300)
        tl_min = min(tl_min, 200)

    # Step 4: Daily distribution
    template = PHASE_TEMPLATES.get(phase, DEFAULT_WEEK)
    start_date = datetime.strptime(start_day, "%Y%m%d")

    daily_plan = []
    consecutive_hard = 0

    for dow in range(7):
        day_type, fraction = template.get(dow, ("easy", 0.10))
        day_date = (start_date + timedelta(days=dow)).strftime("%Y%m%d")
        tl_pct = int(fraction * 100) if day_type != "rest" else 0

        if day_type in ("quality", "long"):
            consecutive_hard += 1
        else:
            consecutive_hard = 0
        if consecutive_hard > MAX_CONSECUTIVE_HARD:
            day_type = "easy"
            tl_pct = 15
            consecutive_hard = 0

        daily_plan.append({
            "date": day_date, "dow": dow + 1,
            "type": day_type, "tl_pct": tl_pct,
        })

    # Step 5: Build workout pool
    try:
        catalog = await fetch_training_library("cn", "zh-CN", category="workout", sport_type="run")
    except Exception:
        catalog = []

    pool_ids = [w.linked_id for w in catalog]  # full catalog

    imported: dict[str, dict] = {}

    async def _import_and_calc(linked_id: str, title: str):
        try:
            result = await import_training_program(auth, linked_id, "workout", 1, title)
            raw = await _fetch_raw_workout(auth, result["imported_id"])
            est = await fetch_program_calculate(auth, raw)
            return {
                "linked_id": linked_id,
                "id": result["imported_id"],
                "title": title,
                "tl": est.get("planTrainingLoad", 50),
                "duration_s": est.get("planDuration", 3600),
            }
        except Exception:
            return None

    # Batch imports to avoid overwhelming the server
    candidates = [w for w in catalog if w.linked_id in pool_ids]
    sem = asyncio.Semaphore(5)  # max 5 concurrent imports

    async def _import_limited(w):
        async with sem:
            return await _import_and_calc(w.linked_id, w.title)

    tasks = [_import_limited(w) for w in candidates]
    results = await asyncio.gather(*tasks)
    for r in results:
        if r:
            imported[r["linked_id"]] = r

    workout_pool = [
        {"id": w["id"], "title": w["title"], "tl": w["tl"],
         "linked_id": w["linked_id"], "duration_s": w["duration_s"]}
        for w in imported.values()
    ]

    # Return framework if Phase 1 only
    if ai_decision is None:
        return {
            "status": "pending",
            "week_start": start_day, "phase": phase,
            "current_state": {
                "load_ratio": current_ratio, "ati": current_ati,
                "cti": current_cti_val, "tired_rate": current_tired_rate,
                "fatigue_state": current_fatigue_state,
            },
            "tl_range": {"min": tl_min, "max": tl_max},
            "daily_plan": daily_plan,
            "workout_pool": workout_pool,
            "pending": {
                "weekly_tl": None,
                "workout_picks": None,
            },
        }

    # ═══════════════════════════════════════════════
    # Phase 2: Validate AI decisions → execute
    # ═══════════════════════════════════════════════

    weekly_tl = ai_decision.get("weekly_tl")
    workout_picks = ai_decision.get("workout_picks", {})
    warnings: list[str] = []

    # Validate weekly TL
    if weekly_tl is None or weekly_tl <= 0:
        return {"status": "rejected", "reason": "weekly_tl is required"}

    if weekly_tl > tl_max * LOAD_RATIO_DANGER:
        return {"status": "rejected",
                "reason": f"TL {weekly_tl} 超出安全上限 {tl_max * LOAD_RATIO_DANGER:.0f}"}

    if weekly_tl > tl_max * LOAD_RATIO_WARNING:
        warnings.append(f"TL {weekly_tl} 在 1.3-1.5 警戒区, 已放行但请确认")

    # Validate workout total vs weekly target — retry if too far off
    picked_total = sum(w.get("tl", 0) for w in workout_picks.values())
    if picked_total > 0 and abs(picked_total - weekly_tl) / weekly_tl > 0.20:
        return {
            "status": "retry",
            "reason": f"匹配总 TL({picked_total})与目标({weekly_tl})偏差 > 20%, 请调整 weekly_tl 后重试",
            "actual_total": picked_total,
            "target": weekly_tl,
        }

    # Schedule
    from coros_api import schedule_workout
    scheduled = []
    for day in daily_plan:
        if day["tl_pct"] <= 0:
            continue
        pick = workout_picks.get(day["date"])
        if pick is None:
            continue
        try:
            await schedule_workout(auth, pick["id"], day["date"], 1)
            scheduled.append({
                "date": day["date"], "type": day["type"],
                "title": pick.get("title", "?"), "tl": pick.get("tl", 0),
            })
        except Exception as e:
            warnings.append(f"{day['date']} 排程失败: {e}")

    # Projection
    projection = None
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
    except Exception as e:
        warnings.append(f"投影获取失败: {e}")

    return {
        "status": "done",
        "warnings": warnings,
        "plan": {
            "week_start": start_day, "phase": phase,
            "weekly_tl": weekly_tl,
            "scheduled": scheduled,
            "projection": projection,
        },
    }
