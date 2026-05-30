"""Generate a weekly training plan — AI embedded in the workflow.

Code enforces safety rules. AI makes all training decisions: which days
to train, what type, how intense, how many rest days.

Two-phase: Phase 1 returns state + catalog + rules → AI builds daily plan
Phase 2 validates plan against rules → imports → schedules → verifies
"""

import asyncio
from datetime import datetime, timedelta

LOAD_RATIO_DANGER = 1.5
LOAD_RATIO_WARNING = 1.3

PHASE_BOUNDS = {
    # quality + long = hard, recovery + easy + long(Z2) = aerobic
    "base":  {"quality": (0, 20),  "long": (20, 35), "recovery": (5, 15), "easy_min": 10, "rest_days": (1, 2)},
    "build": {"quality": (20, 30), "long": (25, 35), "recovery": (5, 15), "easy_min": 10, "rest_days": (1, 2)},
    "peak":  {"quality": (20, 30), "long": (30, 45), "recovery": (5, 15), "easy_min": 10, "rest_days": (1, 2)},
    "taper": {"quality": (15, 25), "long": (15, 30), "recovery": (5, 15), "easy_min": 10, "rest_days": (2, 3)},
}

RULES = [
    "硬日(quality/long)后一天必须是 easy/recovery/rest  [代码强制]",
    "连续硬日不超过 2 天  [代码强制]",
    "至少 1 天完全休息, 周日永远休息  [代码强制]",
    "长距离前后天必须是 easy 或 rest  [代码强制]",
    "周一=恢复或休息  [建议, 代码提醒]",
    "周五=轻松或休息  [建议, 代码提醒]",
    "周 TL 在 coros_recommendation 范围内, 超 1.5 倍硬拒绝  [代码强制]",
]


async def run(auth, start_day: str, phase: str = "base",
              ai_decision: dict | None = None) -> dict:
    """Generate a weekly training plan.

    Phase 1 (ai_decision=None): return state + catalog + rules
    Phase 2 (ai_decision provided): validate → import → schedule → verify
    """
    from coros_api import (
        fetch_training_analysis, fetch_training_library,
        fetch_schedule,
        import_training_program, fetch_program_calculate, _fetch_raw_workout,
    )

    # ═══════════════════════════════════════════════
    # Phase 1: Gather data + rules
    # ═══════════════════════════════════════════════

    # Step 1: Fetch current state
    today = datetime.now().strftime("%Y%m%d")
    two_weeks_ago = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
    analysis = await fetch_training_analysis(auth, two_weeks_ago, today)
    daily = analysis.get("daily_records", [])
    daily_sorted = sorted(daily, key=lambda r: r.get("date", ""), reverse=True)
    latest = daily_sorted[0] if daily_sorted else {}

    current_ratio = latest.get("training_load_ratio", 0.8)
    current_ati = latest.get("ati", 0)
    current_cti_val = latest.get("cti", 50)
    current_tired_rate = latest.get("tired_rate", 0)
    current_fatigue_state = latest.get("tired_rate_state_new", 2)

    # Historical ATI to distinguish "always low" vs "just dropped"
    ati_7d_ago = daily_sorted[min(6, len(daily_sorted)-1)].get("ati", 0) if len(daily_sorted) > 6 else None
    ati_14d_ago = daily_sorted[min(13, len(daily_sorted)-1)].get("ati", 0) if len(daily_sorted) > 13 else None

    # Recent activity context
    train_days_7d = sum(1 for r in daily_sorted[:7] if r.get("training_load", 0) or 0 > 0)
    last_train_day = next((r.get("date") for r in daily_sorted if r.get("training_load", 0) or 0 > 0), None)
    latest_hrv = latest.get("avg_sleep_hrv")
    hrv_baseline = latest.get("baseline")
    hrv_deviation = round((latest_hrv - hrv_baseline) / hrv_baseline * 100, 1) if (latest_hrv and hrv_baseline) else None

    # Step 2: Coros TL recommendation
    week_list = sorted(analysis.get("week_list", []),
                       key=lambda w: w.get("firstDayOfWeek", 0), reverse=True)
    tl_min, tl_max = 350, 500
    for w in week_list:
        if w.get("recomendTlMin") and w.get("recomendTlMax"):
            tl_min = int(w["recomendTlMin"])
            tl_max = int(w["recomendTlMax"])
            break

    if current_ratio >= LOAD_RATIO_DANGER:
        tl_max = min(tl_max, int(current_cti_val * 0.8))
    if current_fatigue_state == 3:
        tl_max = min(tl_max, 300)
        tl_min = min(tl_min, 200)

    # Step 3: Fetch catalog
    try:
        catalog = await fetch_training_library("cn", "zh-CN", category="workout", sport_type="run")
    except Exception:
        catalog = []

    catalog_summary = [
        {"linked_id": w.linked_id, "title": w.title,
         "difficulty": w.difficulties, "sport_types": w.sport_types}
        for w in catalog
    ]

    start_date = datetime.strptime(start_day, "%Y%m%d")
    week_dates = [(start_date + timedelta(days=d)).strftime("%Y%m%d") for d in range(7)]

    # Recommend phase based on state (AI can override)
    if train_days_7d == 0 or (ati_14d_ago and current_ati < ati_14d_ago * 0.5):
        suggested_phase = "base"
    elif current_ratio > 1.3:
        suggested_phase = "taper"
    else:
        suggested_phase = phase

    # Return framework if Phase 1 only
    if ai_decision is None:
        return {
            "status": "pending",
            "week_start": start_day, "phase": phase,
            "suggested_phase": suggested_phase,
            "week_dates": week_dates,  # 7 ISO dates for AI to fill
            "fill": {
                "weekly_tl": {
                    "type": "int",
                    "coros_recommends": f"{tl_min}-{tl_max}",
                    "hint": f"疲劳度={current_fatigue_state} (1=Fresh→偏上限, 2=Normal→中位, 3=Overtrained→下限), "
                           f"负荷比={current_ratio}, "
                           f"ATI趋势: 7天前={ati_7d_ago}, 14天前={ati_14d_ago}, 现在={current_ati} "
                           f"({'下降中→保守' if ati_7d_ago and current_ati < ati_7d_ago * 0.7 else '稳定/上升→可推进'})",
                },
                "daily_plan": {
                    "type": "list[7 days]",
                    "format": '{"date": "YYYYMMDD", "type": "rest|recovery|easy|quality|long", "tl_pct": int}',
                    "hint": "AI 完全自主分配每天的类型和百分比, 只需遵守 rules",
                    "phase_guide": {
                        "base":  "1 次强度/周, 长距离 ~30%, 侧重 Z2 积累",
                        "build": "2 次强度/周, 长距离 ~30%, 质量课比例增加",
                        "peak":  "2 次强度/周, 长距离 ~40%, 最大质量刺激",
                        "taper": "1 次强度/周, 长距离 ~25%, 总量减至正常 70%",
                    },
                },
            },
            "context": {
                "state": {"load_ratio": current_ratio, "ati": current_ati,
                          "cti": current_cti_val, "tired_rate": current_tired_rate,
                          "fatigue_state": current_fatigue_state,
                          "ati_7d_ago": ati_7d_ago, "ati_14d_ago": ati_14d_ago,
                          "train_days_7d": train_days_7d, "last_train_day": last_train_day,
                          "hrv": latest_hrv, "hrv_baseline": hrv_baseline,
                          "hrv_deviation": hrv_deviation},
                "catalog": catalog_summary,
                "rules": RULES,
            },
        }

    # ═══════════════════════════════════════════════
    # Phase 2: Validate → import → schedule → verify
    # ═══════════════════════════════════════════════

    weekly_tl = ai_decision.get("weekly_tl")
    daily_plan = ai_decision.get("daily_plan", [])
    workout_picks = ai_decision.get("workout_picks", {})
    warnings: list[str] = []

    # ── Validate weekly TL ──
    if weekly_tl is None or weekly_tl <= 0:
        return {"status": "rejected", "reason": "weekly_tl is required"}
    if weekly_tl > tl_max * LOAD_RATIO_DANGER:
        return {"status": "rejected",
                "reason": f"TL {weekly_tl} 超出安全上限 {tl_max * LOAD_RATIO_DANGER:.0f}"}
    if weekly_tl > tl_max * LOAD_RATIO_WARNING:
        warnings.append(f"TL {weekly_tl} 在 1.3-1.5 警戒区")

    # ── Validate daily plan against rules ──
    if not daily_plan or len(daily_plan) != 7:
        return {"status": "rejected", "reason": "daily_plan 必须是 7 天"}

    hard_days = 0
    consecutive_hard = 0
    rest_count = 0

    for i, day in enumerate(daily_plan):
        tp = day.get("type", "")
        if tp == "rest":
            rest_count += 1

        if tp in ("quality", "long"):
            hard_days += 1
            consecutive_hard += 1
            # Rule 1: hard day must be preceded by easy/recovery/rest
            if i > 0 and daily_plan[i - 1].get("type") not in ("easy", "recovery", "rest"):
                return {"status": "rejected",
                        "reason": f"{day.get('date')}: 硬日前一天必须是 easy/recovery/rest"}
            # Rule 4: long run must be flanked by easy/rest (both sides)
            if tp == "long":
                if i > 0 and daily_plan[i - 1].get("type") not in ("easy", "rest"):
                    return {"status": "rejected",
                            "reason": f"{day.get('date')}: 长距离前一天必须是 easy/rest"}
                if i < 6 and daily_plan[i + 1].get("type") not in ("easy", "rest"):
                    return {"status": "rejected",
                            "reason": f"{day.get('date')}: 长距离后一天必须是 easy/rest"}
        else:
            consecutive_hard = 0

        # Rule 2: max 2 consecutive hard days
        if consecutive_hard > 2:
            return {"status": "rejected",
                    "reason": f"连续硬日超过 2 天 ({day.get('date')})"}

    # Rule 3: at least 1 rest day, Sunday always rest
    if rest_count < 1:
        return {"status": "rejected", "reason": "一周至少需要 1 天休息"}
    bounds = PHASE_BOUNDS.get(phase, PHASE_BOUNDS["base"])
    rest_lo, rest_hi = bounds["rest_days"]
    if rest_count < rest_lo or rest_count > rest_hi:
        warnings.append(f"休息日 {rest_count} 天 (建议 {rest_lo}-{rest_hi} 天)")
    if daily_plan[6].get("type") != "rest":
        return {"status": "rejected", "reason": "周日必须是休息日"}

    # ── Validate against phase bounds ──
    bounds = PHASE_BOUNDS.get(phase, PHASE_BOUNDS["base"])
    for day in daily_plan:
        tp = day.get("type", "")
        pct = day.get("tl_pct", 0) or 0
        if tp == "quality":
            lo, hi = bounds["quality"]
            if pct < lo or pct > hi:
                warnings.append(f"{day['date']}: quality {pct}% 超出范围 {lo}-{hi}%")
        elif tp == "long":
            lo, hi = bounds["long"]
            if pct < lo or pct > hi:
                warnings.append(f"{day['date']}: long {pct}% 超出范围 {lo}-{hi}%")
        elif tp == "recovery":
            lo, hi = bounds.get("recovery", (5, 15))
            if pct > hi:
                warnings.append(f"{day['date']}: recovery {pct}% 偏重, 建议 ≤{hi}%")
        elif tp == "easy":
            lo = bounds.get("easy_min", 10)
            if pct < lo:
                warnings.append(f"{day['date']}: easy {pct}% 偏低, 建议 ≥{lo}%")

    # ── Type consistency: course title should match day type ──
    TYPE_SIGNALS = {
        "recovery": ("恢复", "基础训练", "轻松"),
        "easy": ("基础训练", "MAF", "轻松"),
        "quality": ("间歇", "VO2max", "节奏", "金字塔", "速度"),
        "long": ("LSD", "长距离", "耐力"),
    }
    for day in daily_plan:
        tp = day.get("type", "")
        w = imported.get(day["date"])
        if not w or tp not in TYPE_SIGNALS:
            continue
        title = w.get("title", "")
        if not any(k in title for k in TYPE_SIGNALS[tp]):
            warnings.append(f"{day['date']} ({tp}): {title} 不是典型的 {tp} 课程")

    # ── Long run must be substantially different from easy days ──
    easy_max = max((w["tl"] for d, w in imported.items()
                    if any(day.get("type") == "easy" for day in daily_plan if day["date"] == d)), default=0)
    long_tl = next((w["tl"] for d, w in imported.items()
                    if any(day.get("type") == "long" for day in daily_plan if day["date"] == d)), 0)
    if long_tl and easy_max and long_tl <= easy_max:
        warnings.append(f"长距离日 TL({long_tl}) <= 轻松日最大 TL({easy_max}), 不应相同")

    # Advisory (best practice, not safety)
    if daily_plan[0].get("type") not in ("recovery", "rest"):
        warnings.append("周一建议恢复或休息")
    if daily_plan[4].get("type") not in ("easy", "rest"):
        warnings.append("周五建议轻松或休息")

    # ── Import selected workouts ──
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

    # ── Validate per-workout TL ──
    day_overshoots = []
    for day in daily_plan:
        w = imported.get(day["date"])
        if not w or day["tl_pct"] <= 0:
            continue
        target = int(weekly_tl * day["tl_pct"] / 100)
        if abs(w["tl"] - target) / target > 0.30:
            day_overshoots.append(
                f"{day['date']} ({day['type']}): 目标{target}TL, 实际{w['tl']}TL"
            )

    # ── Validate total TL ──
    picked_total = sum(w["tl"] for w in imported.values())
    if abs(picked_total - weekly_tl) / weekly_tl > 0.20 or len(day_overshoots) >= 2:
        retry_count = ai_decision.get("_retry_count", 0) + 1
        hint = ("从 catalog 换课重试" if retry_count < 3 else
                f"已重试 {retry_count} 次, catalog 无合适课, 用 create_workout 自建")
        reason_parts = [f"总 TL({picked_total})vs 目标({weekly_tl})"]
        if day_overshoots:
            reason_parts.append(f"{len(day_overshoots)}门课偏差>30%")
        return {
            "status": "retry",
            "retry_count": retry_count,
            "reason": "; ".join(reason_parts),
            "target": weekly_tl,
            "actual_total": picked_total,
            "per_workout_tl": {d: {"title": w["title"], "tl": w["tl"]}
                               for d, w in imported.items()},
            "day_overshoots": day_overshoots,
            "warnings": warnings,
            "hint": hint,
        }

    # ── Schedule ──
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

    # ── Projection ──
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
