"""Training recommendation — "What should I do today?"."""

from typing import Any


def _zone_target(intensity: str, user_profile: dict) -> dict | None:
    """Build personalized HR zone target from user profile."""
    zone_model = user_profile.get("hr_zone_type", 1) or 1
    zones = (user_profile.get("zones") or {}).get(zone_model)
    if not zones:
        return None

    zone_map = {"Rest": 0, "Easy": 2, "Moderate": 3, "Hard": 5}
    zone_idx = zone_map.get(intensity, 2)
    try:
        entry = zones[zone_idx - 1]
    except (IndexError, TypeError):
        return None
    low = entry.get("hrLow")
    high = entry.get("hrHigh")
    if low and high:
        return {
            "zone": zone_idx,
            "model": {1: "MaxHR", 2: "%HRR", 3: "%LTHR"}.get(zone_model,
                                                             "MaxHR"),
            "bpm_low": low,
            "bpm_high": high,
        }
    return None


def generate_recommendation(
    readiness: dict,
    fatigue: dict,
    training_status: dict,
    schedule: list[dict] | None = None,
    user_profile: dict | None = None,
) -> dict:
    """Generate today's training recommendation from readiness x fatigue x status.

    Returns dict with: primary, alternative, intensity, duration_minutes, why,
    zone_target.
    """
    user_profile = user_profile or {}
    r_score = readiness.get("score", "Moderate")
    f_level = fatigue.get("level", "Normal")
    t_state = training_status.get("state", "Insufficient Data")

    # Decision matrix
    if f_level == "Overtrained" or t_state == "Excessive":
        intensity, dur, primary, why = (
            "Rest", 0,
            "Complete rest — overtraining or excessive load indicators",
            "Overtraining/excessive load indicators present")
    elif r_score == "Recover":
        intensity, dur, primary, why = (
            "Easy", 30,
            "Active recovery — very low intensity or full rest",
            "Readiness is low, prioritize recovery")
    elif r_score == "Rest":
        intensity, dur, primary, why = (
            "Rest", 0,
            "Full rest day recommended",
            "Readiness critically low")
    elif (r_score == "Ready" and f_level == "Fresh"
          and t_state == "Performance"):
        intensity, dur, primary, why = (
            "Hard", 75,
            "Race-specific session or high-intensity intervals",
            "Peak performance window — great day for quality work")
    elif (r_score == "Ready"
          and (f_level == "Fresh" or f_level == "Normal")
          and t_state == "Optimized"):
        intensity, dur, primary, why = (
            "Hard", 60,
            "Threshold/tempo session — good day for hard training",
            "Optimal training zone with adequate recovery")
    elif (r_score == "Ready" and f_level == "Fresh"
          and t_state == "Maintaining"):
        intensity, dur, primary, why = (
            "Moderate", 60,
            "Moderate build session — progressive medium-long run",
            "Solid fitness base, building volume")
    elif (r_score == "Ready" and f_level == "Normal"
          and t_state == "Maintaining"):
        intensity, dur, primary, why = (
            "Moderate", 50,
            "Standard training day — quality but not max effort",
            "Normal readiness with maintained fitness")
    elif r_score == "Ready" and f_level == "Fatigued":
        intensity, dur, primary, why = (
            "Easy", 45,
            "Active recovery or easy run — monitor how you feel",
            "Ready signals are good but fatigue is present")
    elif (r_score == "Moderate"
          and (f_level == "Fresh" or f_level == "Normal")
          and t_state == "Optimized"):
        intensity, dur, primary, why = (
            "Moderate", 60,
            "Technique-focused session — moderate intensity with form emphasis",
            "Moderate readiness, optimized training zone")
    elif r_score == "Moderate":
        intensity, dur, primary, why = (
            "Easy", 45,
            "Easy run or cross-training — keep it light",
            "Moderate readiness — focus on consistency, not intensity")
    elif t_state == "Resuming":
        intensity, dur, primary, why = (
            "Easy", 30,
            "Ease back in — short, easy session",
            "Resuming training — gradual return")
    else:
        intensity, dur, primary, why = (
            "Moderate", 50,
            "Standard training day",
            "Default recommendation — listen to your body")

    zone_target = _zone_target(intensity, user_profile)

    # Alternative: scheduled workout today
    alternative = None
    if schedule:
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        entities = (schedule if isinstance(schedule, list)
                    else schedule.get("entities", []))
        for entity in entities:
            if (isinstance(entity, dict)
                    and entity.get("happenDay") == today):
                alt_name = entity.get("name") or "Scheduled workout"
                alternative = (
                    f"Today's plan: {alt_name} — "
                    f"adjust based on readiness ({r_score})")
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
