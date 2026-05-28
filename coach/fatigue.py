"""Fatigue assessment — "How tired am I?"."""

from . import _avg, _safe_float
from .thresholds import (
    SLEEP_OPTIMAL_MINUTES,
    SLEEP_DEBT_ALERT_HOURS,
    FRESH_TIRED_RATE,
    FATIGUED_TIRED_RATE,
    OVERTRAINED_TIRED_RATE,
)


def _tired_rate_signal(daily_records: list[dict]) -> tuple[str, str]:
    """Primary fatigue signal from COROS tired_rate_state_new or tired_rate fallback."""
    if not daily_records:
        return "Normal", "No tired_rate data → default Normal"

    latest = daily_records[0]
    state = latest.get("tired_rate_state_new")
    tired_rate = latest.get("tired_rate")

    # COROS tired_rate_state_new enum
    if state == 1:
        return "Fresh", "tired_rate_state=1 (well recovered)"
    if state == 2:
        rate_str = f" (tired_rate={tired_rate:.0f})" if tired_rate is not None else ""
        return "Normal", f"tired_rate_state=2 (normal fatigue){rate_str}"
    if state == 3:
        return "Fatigued", "tired_rate_state=3 (fatigue accumulating)"

    # Numeric fallback
    tr = _safe_float(tired_rate)
    if tr is None:
        return "Normal", "No tired_rate signal → default Normal"

    if tr <= FRESH_TIRED_RATE:
        return "Fresh", f"tired_rate={tr:.0f} (≤{FRESH_TIRED_RATE})"
    if tr >= OVERTRAINED_TIRED_RATE:
        return "Overtrained", f"tired_rate={tr:.0f} (≥{OVERTRAINED_TIRED_RATE})"
    if tr >= FATIGUED_TIRED_RATE:
        return "Fatigued", f"tired_rate={tr:.0f} (≥{FATIGUED_TIRED_RATE})"
    return "Normal", f"tired_rate={tr:.0f} (between {FRESH_TIRED_RATE} and {FATIGUED_TIRED_RATE})"


def _sleep_debt_signal(sleep_records: list[dict]) -> tuple[str, str] | None:
    """Secondary fatigue signal: sleep debt."""
    if not sleep_records or len(sleep_records) < 3:
        return None

    recent = sleep_records[:3]
    avg_dur = _avg([r.get("total_duration_minutes") for r in recent
                    if r.get("total_duration_minutes") is not None])
    if avg_dur is None:
        return None

    debt_hours = (SLEEP_OPTIMAL_MINUTES - avg_dur) / 60
    if debt_hours >= SLEEP_DEBT_ALERT_HOURS:
        return "amplify", f"Sleep debt {debt_hours:.1f}h → amplifies fatigue"
    return "ok", f"Sleep debt {debt_hours:.1f}h → acceptable"


def _hrv_fatigue_signal(daily_records: list[dict]) -> tuple[str, str] | None:
    """Check if HRV is trending down (sympathetic dominance)."""
    hrvs = [(r.get("avg_sleep_hrv"), r.get("baseline"))
            for r in daily_records if r.get("avg_sleep_hrv") is not None]
    if len(hrvs) < 3:
        return None

    recent = _avg([h for h, _ in hrvs[:3]])
    previous = _avg([h for h, _ in hrvs[3:7]]) if len(hrvs) > 3 else recent
    if recent is None or previous is None:
        return None

    change_pct = ((recent - previous) / previous) * 100 if previous > 0 else 0
    if change_pct < -5:
        return "amplify", f"HRV trending down ({change_pct:+.1f}%) → possible accumulating fatigue"
    return "ok", f"HRV stable or rising ({change_pct:+.1f}%)"


def _stress_signal(daily_health: list[dict]) -> tuple[str, str] | None:
    """Check if average stress is elevated."""
    if not daily_health:
        return None
    recent = daily_health[:3]
    avg_stress = _avg([r.get("avg_stress") for r in recent
                       if r.get("avg_stress") is not None])
    if avg_stress is None:
        return None

    if avg_stress > 45:
        return "amplify", f"High stress avg {avg_stress:.0f} → amplifies fatigue"
    if avg_stress < 25:
        return "reduce", f"Low stress avg {avg_stress:.0f} → helps recovery"
    return "ok", f"Stress avg {avg_stress:.0f} → normal"



def assess_fatigue(
    daily_records: list[dict],
    sleep_records: list[dict] | None = None,
    daily_health: list[dict] | None = None,
) -> dict:
    """Determine fatigue level from tired_rate + sleep + HRV + stress signals.

    Returns dict with: level (Fresh/Normal/Fatigued/Overtrained),
    fatigue_rate, contributing_factors.
    """
    sleep_records = sleep_records or []
    daily_health = daily_health or []

    level, reason = _tired_rate_signal(daily_records)
    factors = [reason]

    # Sleep debt amplifies fatigue
    sleep_sig = _sleep_debt_signal(sleep_records)
    if sleep_sig:
        sig_type, sig_reason = sleep_sig
        factors.append(f"Sleep: {sig_reason}")
        if sig_type == "amplify" and level == "Normal":
            level = "Fatigued"
        elif sig_type == "amplify" and level == "Fresh":
            level = "Normal"

    # HRV decline amplifies fatigue
    hrv_sig = _hrv_fatigue_signal(daily_records)
    if hrv_sig:
        _, hrv_reason = hrv_sig
        factors.append(f"HRV: {hrv_reason}")

    # Stress amplifies/reduces fatigue
    stress_sig = _stress_signal(daily_health)
    if stress_sig:
        sig_type, stress_reason = stress_sig
        factors.append(f"Stress: {stress_reason}")
        if sig_type == "amplify" and level == "Normal":
            level = "Fatigued"
        elif sig_type == "amplify" and level == "Fresh":
            level = "Normal"

    fatigue_rate = None
    if daily_records:
        latest = daily_records[0]
        fatigue_rate = latest.get("tired_rate")

    return {
        "level": level,
        "fatigue_rate": fatigue_rate,
        "contributing_factors": factors,
    }
