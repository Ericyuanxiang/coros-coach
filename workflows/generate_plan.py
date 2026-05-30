"""Generate a weekly training plan — AI embedded in the workflow.

Two-phase: Phase 1 builds framework → AI fills decisions → Phase 2 imports + validates + schedules.

Usage:
  framework = await run(auth, "20260601", "build")
  # AI picks workouts from catalog, fills weekly_tl + picks
  plan = await run(auth, "20260601", "build", ai_decision={...})
"""

import asyncio
from datetime import datetime, timedelta

# ── Scheduling rules (not hardcoded templates) ──
# AI can override day type/pct within these constraints

def _build_daily_plan(phase: str) -> list[dict]:
    """Generate a 7-day plan from phase rules. AI can override within constraints.

    Phase params:
      rest_days:      which days are always rest (Sunday + Friday always)
      quality_count:  1-2 quality sessions/week
      long_pct:       Saturday long run share
    """
    phase_cfg = {
        # rest_extra: additional rest days beyond Sunday (dow=6)
        "base":  {"rest_extra": [4],    "quality": 1, "long_pct": 0.30, "quality_pct": 0.20, "recovery_pct": 0.15},
        "build": {"rest_extra": [4],    "quality": 2, "long_pct": 0.30, "quality_pct": 0.25, "recovery_pct": 0.15},
        "peak":  {"rest_extra": [0, 4], "quality": 2, "long_pct": 0.40, "quality_pct": 0.20, "recovery_pct": 0.10},
        "taper": {"rest_extra": [0, 4], "quality": 1, "long_pct": 0.25, "quality_pct": 0.15, "recovery_pct": 0.10},
    }
    cfg = phase_cfg.get(phase, phase_cfg["base"])
    plan = {}

    # Sunday always rest. Phase config controls extra rest days
    plan[6] = ("rest", 0.0)
    for d in cfg["rest_extra"]:
        plan[d] = ("rest", 0.0)

    # Saturday long
    plan[5] = ("long", cfg["long_pct"])

    # Quality sessions
    if cfg["quality"] == 1:
        plan[2] = ("quality", cfg["quality_pct"])  # Wednesday
    else:
        plan[1] = ("quality", cfg["quality_pct"])  # Tuesday
        plan[3] = ("quality", cfg["quality_pct"])  # Thursday

    # Monday recovery (if not rest)
    if 0 not in plan:
        plan[0] = ("recovery", cfg["recovery_pct"])

    # Remaining days = easy
    remaining = 1.0 - sum(f for _, f in plan.values())
    easy_days = [d for d in range(7) if d not in plan]
    if easy_days:
        each = remaining / len(easy_days)
        for d in easy_days:
            plan[d] = ("easy", round(each, 2))

    return plan

LOAD_RATIO_DANGER = 1.5
LOAD_RATIO_WARNING = 1.3
MAX_CONSECUTIVE_HARD = 2


async def run(auth, start_day: str, phase: str = "base",
              ai_decision: dict | None = None) -> dict:
    """Generate a weekly training plan.

    Phase 1 (ai_decision=None): return framework + catalog for AI
    Phase 2 (ai_decision provided): import selected workouts, validate, schedule
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

    daily_sorted = sorted(daily, key=lambda r: r.get("date", ""), reverse=True)
    latest = daily_sorted[0] if daily_sorted else {}
    current_ratio = latest.get("training_load_ratio", 0.8)
    current_ati = latest.get("ati", 0)
    current_cti_val = latest.get("cti", 50)
    current_tired_rate = latest.get("tired_rate", 0)
    current_fatigue_state = latest.get("tired_rate_state_new", 2)

    # Step 2: Coros TL recommendation — latest week with values
    week_list = sorted(analysis.get("week_list", []),
                       key=lambda w: w.get("firstDayOfWeek", 0), reverse=True)
    tl_min, tl_max = 350, 500
    for w in week_list:
        if w.get("recomend_tl_min") and w.get("recomend_tl_max"):
            tl_min = int(w["recomend_tl_min"])
            tl_max = int(w["recomend_tl_max"])
            break

    # Step 3: Safety caps (only danger zone — 1.5 is hard limit)
    if current_ratio >= LOAD_RATIO_DANGER:
        tl_max = min(tl_max, int(current_cti_val * 0.8))
    if current_fatigue_state == 3:
        tl_max = min(tl_max, 300)
        tl_min = min(tl_min, 200)

    # Step 4: Daily distribution — rules-based, not fixed template
    plan_map = _build_daily_plan(phase)
    start_date = datetime.strptime(start_day, "%Y%m%d")

    daily_plan = []
    consecutive_hard = 0

    for dow in range(7):
        day_type, fraction = plan_map.get(dow, ("easy", 0.10))
        day_date = (start_date + timedelta(days=dow)).strftime("%Y%m%d")
        tl_pct = int(fraction * 100) if day_type != "rest" else 0

        if day_type in ("quality", "long"):
            consecutive_hard += 1
        else:
            consecutive_hard = 0
        if consecutive_hard > MAX_CONSECUTIVE_HARD:
            day_type = "easy"
            # Use the first easy/recovery day fraction as fallback
            easy_frac = 0.15
            for _dow, (_dt, _frac) in plan_map.items():
                if _dt in ("easy", "recovery"):
                    easy_frac = _frac
                    break
            tl_pct = int(easy_frac * 100)
            consecutive_hard = 0

        daily_plan.append({
            "date": day_date, "dow": dow + 1,
            "type": day_type, "tl_pct": tl_pct,
        })

    # Step 5: Fetch catalog (no import — AI picks from this)
    try:
        catalog = await fetch_training_library("cn", "zh-CN", category="workout", sport_type="run")
    except Exception:
        catalog = []

    catalog_summary = [
        {"linked_id": w.linked_id, "title": w.title,
         "difficulty": w.difficulties, "sport_types": w.sport_types}
        for w in catalog
    ]

    # Return framework if Phase 1 only — fill first, context second
    if ai_decision is None:
        return {
            "status": "pending",
            "week_start": start_day, "phase": phase,
            "fill": {
                "weekly_tl": {
                    "type": "int",
                    "coros_recommends": f"{tl_min}-{tl_max}",
                    "hint": f"疲劳度={current_fatigue_state}(1=Fresh→偏上限, 2=Normal→中位, 3=Overtrained→下限), "
                           f"负荷比={current_ratio}({'>1.5危险' if current_ratio>=LOAD_RATIO_DANGER else '<1.5安全'})",
                },
                "workout_picks": {
                    "type": "dict[date, linked_id]",
                    "from": "catalog below",
                    "hint": "按 daily_plan 的 type 从 catalog 选课, 优先标题含关键词: 恢复→恢复, 轻松→基础/MAF, 强度→间歇/VO2max/节奏, 长→LSD/长距离",
                },
            },
            "context": {
                "state": {"load_ratio": current_ratio, "ati": current_ati,
                          "cti": current_cti_val, "tired_rate": current_tired_rate,
                          "fatigue_state": current_fatigue_state},
                "daily_plan": daily_plan,
                "catalog": catalog_summary,
            },
        }

    # ═══════════════════════════════════════════════
    # Phase 2: Import selected → validate → schedule
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
        warnings.append(f"TL {weekly_tl} 在 1.3-1.5 警戒区")

    # Import only selected workouts, calculate TL
    imported: dict[str, dict] = {}
    for day_date, pick in workout_picks.items():
        linked_id = pick.get("linked_id")
        if not linked_id:
            continue
        try:
            result = await import_training_program(auth, linked_id, "workout", 1,
                                                   pick.get("title", "import"))
            wid = result["imported_id"]
            raw = await _fetch_raw_workout(auth, wid)
            est = await fetch_program_calculate(auth, raw)
            imported[day_date] = {
                "id": wid,
                "title": pick.get("title", "?"),
                "tl": est.get("planTrainingLoad", 50),
                "duration_s": est.get("planDuration", 3600),
            }
        except Exception as e:
            warnings.append(f"{day_date} 导入失败: {e}")

    if not imported:
        return {"status": "rejected", "reason": "没有成功导入任何课程"}

    # Validate total vs target
    picked_total = sum(w["tl"] for w in imported.values())
    if abs(picked_total - weekly_tl) / weekly_tl > 0.20:
        return {
            "status": "retry",
            "reason": f"匹配总 TL({picked_total})与目标({weekly_tl})偏差 > 20%, 请换课重试",
            "target": weekly_tl,
            "actual_total": picked_total,
            "per_workout_tl": {d: {"title": w["title"], "tl": w["tl"]}
                               for d, w in imported.items()},
            "warnings": warnings,
        }

    # Schedule
    from coros_api import schedule_workout
    scheduled = []
    for day in daily_plan:
        w = imported.get(day["date"])
        if w is None:
            continue
        try:
            await schedule_workout(auth, w["id"], day["date"], 1)
            scheduled.append({
                "date": day["date"], "type": day["type"],
                "title": w["title"], "tl": w["tl"],
            })
        except Exception as e:
            warnings.append(f"{day['date']} 排程失败: {e}")

    # Projection
    projection = None
    try:
        end_day = (start_date + timedelta(days=6)).strftime("%Y%m%d")
        sched = await fetch_schedule(auth, start_day, end_day)
        weeks = sched.get("weekStages", [])
        target_week = int(start_day)
        week_data = next((w for w in weeks if w.get("firstDayInWeek") == target_week), None)
        if week_data:
            ws = week_data.get("trainSum", {})
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
