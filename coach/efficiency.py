"""Training efficiency — pace vs heart-rate crossover analysis.

Answers: at the same pace, is my heart rate going down over time?

Data source:
  - fetch_activities() → ActivitySummary: avg_hr, distance_meters,
    duration_seconds, sport_type, start_time, training_load
"""


def analyse_efficiency(activities: list[dict]) -> dict:
    """Compare pace-vs-HR trends over time for running activities.

    Returns overall efficiency trend + per-comparison details.
    """
    runs = [
        a for a in activities
        if a.get("sport_type") in (100, 102, 103)   # running variants
        and a.get("avg_hr")
        and a.get("distance_meters")
        and a.get("duration_seconds")
    ]
    if len(runs) < 2:
        return {"trend": "Insufficient data", "comparisons": []}

    # Calculate pace (sec/km) for each run
    for r in runs:
        dist_km = r["distance_meters"] / 1000
        r["_pace"] = r["duration_seconds"] / dist_km if dist_km > 0 else None

    # Sort by date
    runs.sort(key=lambda r: r.get("start_time", ""))

    comparisons = []
    improving = 0
    declining = 0

    for i in range(len(runs) - 1):
        a, b = runs[i], runs[i + 1]
        if not a["_pace"] or not b["_pace"]:
            continue

        pace_diff_pct = abs(b["_pace"] - a["_pace"]) / a["_pace"] * 100
        # Only compare runs with similar pace (< 5% difference)
        if pace_diff_pct > 5:
            continue

        hr_diff = b["avg_hr"] - a["avg_hr"]
        a_pace_str = _fmt_pace(a["_pace"])
        b_pace_str = _fmt_pace(b["_pace"])

        if hr_diff < -2:
            improving += 1
            direction = "improving"
        elif hr_diff > 2:
            declining += 1
            direction = "declining"
        else:
            direction = "stable"

        comparisons.append({
            "date_a": a.get("start_time"),
            "date_b": b.get("start_time"),
            "pace": f"{a_pace_str} vs {b_pace_str}",
            "hr_a": a["avg_hr"],
            "hr_b": b["avg_hr"],
            "hr_delta": hr_diff,
            "direction": direction,
        })

    if improving > declining:
        trend = "improving"
    elif declining > improving:
        trend = "declining"
    elif comparisons:
        trend = "stable"
    else:
        trend = "Insufficient data"

    return {
        "trend": trend,
        "improving_pairs": improving,
        "declining_pairs": declining,
        "total_pairs": len(comparisons),
        "comparisons": comparisons[:10],  # last 10 comparisons
    }


def analyse_pace_at_hr(activities: list[dict], target_hr: int = 150) -> dict:
    """At a given heart rate, is pace improving over time?"""
    runs = [
        a for a in activities
        if a.get("sport_type") in (100, 102, 103)
        and a.get("avg_hr")
        and a.get("distance_meters")
        and a.get("duration_seconds")
    ]
    if len(runs) < 2:
        return {"trend": "Insufficient data"}

    for r in runs:
        dist_km = r["distance_meters"] / 1000
        r["_pace"] = r["duration_seconds"] / dist_km if dist_km > 0 else None

    runs.sort(key=lambda r: r.get("start_time", ""))

    # Find runs near target HR (±5 bpm)
    near_hr = [r for r in runs if abs(r["avg_hr"] - target_hr) <= 5]
    if len(near_hr) < 2:
        return {"trend": "Insufficient data at this HR", "target_hr": target_hr}

    half = max(1, len(near_hr) // 2)
    first_avg = sum(r["_pace"] for r in near_hr[:half]) / half
    last_avg = sum(r["_pace"] for r in near_hr[-half:]) / half
    delta_pct = ((last_avg - first_avg) / first_avg * 100) if first_avg else 0

    return {
        "target_hr": target_hr,
        "sample_count": len(near_hr),
        "first_3_pace": _fmt_pace(first_avg),
        "last_3_pace": _fmt_pace(last_avg),
        "pace_change_pct": round(delta_pct, 1),
        "trend": "improving" if delta_pct < -1 else ("declining" if delta_pct > 1 else "stable"),
    }


def _fmt_pace(sec_per_km: float) -> str:
    """Convert sec/km → m:ss/km."""
    if not sec_per_km or sec_per_km <= 0:
        return "?"
    m = int(sec_per_km // 60)
    s = int(sec_per_km % 60)
    return f"{m}:{s:02d}"
