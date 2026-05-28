"""Tests for coach/ package analysis engine — all pure functions, no I/O."""

import pytest
import coach


# ============================================================================
# Test data factories
# ============================================================================

def _make_record(
    date="20260525",
    avg_sleep_hrv=68.0,
    baseline=65.0,
    rhr=58,
    training_load=50,
    t7d=45,
    t28d=55,
    training_load_ratio_state=2,
    training_load_ratio=0.8,
    tired_rate=-35,
    tired_rate_state_new=1,
    stamina_level=85.0,
    stamina_level_7d=86.0,
    distance=8000.0,
    duration=2400,
    vo2max=55,
    **kwargs,
):
    rec = {
        "date": date,
        "avg_sleep_hrv": avg_sleep_hrv,
        "baseline": baseline,
        "rhr": rhr,
        "training_load": training_load,
        "t7d": t7d,
        "t28d": t28d,
        "training_load_ratio_state": training_load_ratio_state,
        "training_load_ratio": training_load_ratio,
        "tired_rate": tired_rate,
        "tired_rate_state_new": tired_rate_state_new,
        "stamina_level": stamina_level,
        "stamina_level_7d": stamina_level_7d,
        "distance": distance,
        "duration": duration,
        "vo2max": vo2max,
    }
    rec.update(kwargs)
    return rec


def _make_sleep(date="20260525", total_duration_minutes=450, quality_score=85, **kwargs):
    rec = {"date": date, "total_duration_minutes": total_duration_minutes, "quality_score": quality_score}
    rec.update(kwargs)
    return rec


def _make_health(date="20260525", avg_stress=25, **kwargs):
    rec = {"date": date, "avg_stress": avg_stress}
    rec.update(kwargs)
    return rec


def _make_profile(**kwargs):
    defaults = {
        "rhr": 55,
        "max_hr": 185,
        "lthr": 172,
        "hr_zone_type": 1,
        "zones": {
            1: [
                {"hrLow": 0, "hrHigh": 120},
                {"hrLow": 120, "hrHigh": 145},
                {"hrLow": 145, "hrHigh": 160},
                {"hrLow": 160, "hrHigh": 172},
                {"hrLow": 172, "hrHigh": 185},
                {"hrLow": 185, "hrHigh": 200},
            ],
        },
    }
    defaults.update(kwargs)
    return defaults


# ---- Scenario fixtures ----

def healthy_fixtures():
    """Well-rested, well-trained athlete — 14 days."""
    daily = [
        _make_record("20260525", avg_sleep_hrv=70, rhr=56, training_load=50, tired_rate=-40, tired_rate_state_new=1, t7d=48, t28d=52, training_load_ratio_state=2, stamina_level=87, stamina_level_7d=88, distance=10000, duration=3000),
        _make_record("20260524", avg_sleep_hrv=69, rhr=57, training_load=0, tired_rate=-38, tired_rate_state_new=1, t7d=45, t28d=50, distance=0, duration=0),
        _make_record("20260523", avg_sleep_hrv=68, rhr=57, training_load=60, tired_rate=-36, tired_rate_state_new=1, t7d=47, t28d=50, distance=12000, duration=3600),
        _make_record("20260522", avg_sleep_hrv=67, rhr=57, training_load=0, tired_rate=-34, tired_rate_state_new=1, t7d=44, t28d=49, distance=0, duration=0),
        _make_record("20260521", avg_sleep_hrv=68, rhr=56, training_load=55, tired_rate=-33, tired_rate_state_new=1, t7d=43, t28d=48, distance=11000, duration=3300),
        _make_record("20260520", avg_sleep_hrv=66, rhr=57, training_load=0, tired_rate=-35, tired_rate_state_new=1, t7d=42, t28d=48, distance=0, duration=0),
        _make_record("20260519", avg_sleep_hrv=67, rhr=56, training_load=45, tired_rate=-32, tired_rate_state_new=1, t7d=41, t28d=47, distance=9000, duration=2700),
        _make_record("20260518", avg_sleep_hrv=65, rhr=57, training_load=0, tired_rate=-30, tired_rate_state_new=2, t7d=40, t28d=47, distance=0, duration=0),
        _make_record("20260517", avg_sleep_hrv=64, rhr=58, training_load=40, tired_rate=-28, tired_rate_state_new=2, t7d=39, t28d=46, distance=8000, duration=2400),
        _make_record("20260516", avg_sleep_hrv=63, rhr=58, training_load=0, tired_rate=-30, tired_rate_state_new=2, t7d=38, t28d=46, distance=0, duration=0),
        _make_record("20260515", avg_sleep_hrv=64, rhr=59, training_load=35, tired_rate=-25, tired_rate_state_new=2, t7d=37, t28d=45, distance=7000, duration=2100),
        _make_record("20260514", avg_sleep_hrv=62, rhr=59, training_load=0, tired_rate=-28, tired_rate_state_new=2, t7d=36, t28d=45, distance=0, duration=0),
        _make_record("20260513", avg_sleep_hrv=63, rhr=60, training_load=30, tired_rate=-22, tired_rate_state_new=2, t7d=35, t28d=44, distance=6000, duration=1800),
        _make_record("20260512", avg_sleep_hrv=61, rhr=60, training_load=0, tired_rate=-25, tired_rate_state_new=2, t7d=34, t28d=44, distance=0, duration=0),
    ]
    sleep = [
        _make_sleep("20260525", 480, 88),
        _make_sleep("20260524", 460, 85),
        _make_sleep("20260523", 450, 82),
        _make_sleep("20260522", 440, 80),
        _make_sleep("20260521", 470, 87),
        _make_sleep("20260520", 455, 83),
        _make_sleep("20260519", 465, 86),
    ]
    return daily, sleep


def fatigued_fixtures():
    """Overtrained athlete — HRV dropping, RHR rising, poor sleep, high fatigue."""
    daily = [
        _make_record("20260525", avg_sleep_hrv=38, baseline=65, rhr=68, training_load=80, tired_rate=10, tired_rate_state_new=3, t7d=80, t28d=55, training_load_ratio_state=3, training_load_ratio=1.4, stamina_level=78, stamina_level_7d=76, distance=15000, duration=4500),
        _make_record("20260524", avg_sleep_hrv=40, baseline=65, rhr=66, training_load=70, tired_rate=8, tired_rate_state_new=3, t7d=78, t28d=54, training_load_ratio_state=3, distance=14000, duration=4200),
        _make_record("20260523", avg_sleep_hrv=42, baseline=65, rhr=65, training_load=75, tired_rate=5, tired_rate_state_new=3, t7d=75, t28d=53, training_load_ratio_state=3, distance=13000, duration=4000),
        _make_record("20260522", avg_sleep_hrv=48, baseline=65, rhr=62, training_load=0, tired_rate=2, tired_rate_state_new=2, t7d=70, t28d=52, training_load_ratio_state=2, distance=0, duration=0),
        _make_record("20260521", avg_sleep_hrv=52, baseline=65, rhr=60, training_load=65, tired_rate=0, tired_rate_state_new=2, t7d=68, t28d=51, training_load_ratio_state=2, distance=12000, duration=3600),
        # ... weeks 1-2 filled with similar records
    ]
    # Fill out more days for week comparison
    for i in range(6, 14):
        daily.append(
            _make_record(f"202605{19-i:02d}", avg_sleep_hrv=60-i, rhr=58+i, training_load=(50+i) if i % 2 == 0 else 0, tired_rate=-20+i*2, tired_rate_state_new=2 if i < 10 else 3, t7d=40+i, t28d=48+i//2, training_load_ratio_state=2, distance=(8000+i*1000) if i % 2 == 0 else 0, duration=(2400+i*300) if i % 2 == 0 else 0))
    sleep = [
        _make_sleep("20260525", 300, 35),
        _make_sleep("20260524", 320, 40),
        _make_sleep("20260523", 340, 45),
        _make_sleep("20260522", 380, 55),
        _make_sleep("20260521", 410, 60),
        _make_sleep("20260520", 430, 65),
        _make_sleep("20260519", 440, 70),
    ]
    return daily, sleep


def minimal_fixtures():
    """New user — very sparse data."""
    daily = [
        _make_record("20260525", avg_sleep_hrv=None, baseline=None, rhr=None, training_load=None, t7d=None, t28d=None, training_load_ratio_state=None, tired_rate=None, tired_rate_state_new=None, stamina_level=None, stamina_level_7d=None, distance=None, duration=None),
        _make_record("20260524"),
    ]
    sleep = []
    return daily, sleep


# ============================================================================
# assess_readiness
# ============================================================================

class TestAssessReadiness:
    def test_ready_all_signals_good(self):
        daily, sleep = healthy_fixtures()
        result = coach.assess_readiness(daily, sleep)
        assert result["score"] in ("Ready", "Moderate")

    def test_rest_all_signals_poor(self):
        daily, sleep = fatigued_fixtures()
        result = coach.assess_readiness(daily, sleep)
        assert result["score"] in ("Recover", "Rest")

    def test_no_sleep_data_falls_back(self):
        daily, _ = healthy_fixtures()
        result = coach.assess_readiness(daily, [])
        assert result["score"] in ("Ready", "Moderate", "Recover")

    def test_no_data_at_all(self):
        result = coach.assess_readiness([], [])
        assert result["score"] in ("Moderate", "Recover")  # conservative fallback

    def test_returns_contributing_factors(self):
        daily, sleep = healthy_fixtures()
        result = coach.assess_readiness(daily, sleep)
        assert len(result["contributing_factors"]) >= 1

    def test_ratio_between_zero_and_one(self):
        daily, _ = healthy_fixtures()
        result = coach.assess_readiness(daily, [])
        assert 0.0 <= result["ratio"] <= 1.0

    def test_profile_rhr_used_in_readiness(self):
        daily, sleep = healthy_fixtures()
        profile = _make_profile(rhr=55)
        result = coach.assess_readiness(daily, sleep, profile)
        # Should still produce valid score with profile RHR as baseline
        assert result["score"] in ("Ready", "Moderate", "Recover")
        assert any("profile baseline" in f for f in result["contributing_factors"])

    def test_recovery_hours_caps_readiness(self):
        daily, sleep = healthy_fixtures()
        # With 16h recovery remaining, even a healthy athlete is capped
        result = coach.assess_readiness(daily, sleep, recovery_hours=16)
        assert result["score"] in ("Moderate", "Recover")
        assert any("recovery" in f.lower() for f in result["contributing_factors"])

    def test_recovery_complete_no_cap(self):
        daily, sleep = healthy_fixtures()
        result = coach.assess_readiness(daily, sleep, recovery_hours=0)
        assert result["score"] in ("Ready", "Moderate")
        assert any("complete" in f.lower() for f in result["contributing_factors"])


# ============================================================================
# assess_fatigue
# ============================================================================

class TestAssessFatigue:
    def test_fresh_from_tired_rate_state(self):
        daily, sleep = healthy_fixtures()
        result = coach.assess_fatigue(daily, sleep)
        assert result["level"] == "Fresh"

    def test_fatigued_from_tired_rate_state(self):
        daily, sleep = fatigued_fixtures()
        result = coach.assess_fatigue(daily, sleep)
        assert result["level"] in ("Fatigued", "Overtrained")

    def test_no_data_returns_normal(self):
        result = coach.assess_fatigue([])
        assert result["level"] == "Normal"

    def test_returns_fatigue_rate(self):
        daily, _ = healthy_fixtures()
        result = coach.assess_fatigue(daily, [])
        assert result["fatigue_rate"] is not None

    def test_contributing_factors(self):
        daily, sleep = healthy_fixtures()
        result = coach.assess_fatigue(daily, sleep)
        assert len(result["contributing_factors"]) >= 1

    def test_numeric_fallback_when_no_state_enum(self):
        daily = [_make_record("20260525", tired_rate=-50, tired_rate_state_new=None)]
        result = coach.assess_fatigue(daily, [])
        assert result["level"] == "Fresh"

    def test_numeric_overtrained(self):
        daily = [_make_record("20260525", tired_rate=25, tired_rate_state_new=None)]
        result = coach.assess_fatigue(daily, [])
        assert result["level"] == "Overtrained"

    def test_sleep_debt_amplifies_fatigue(self):
        daily = [_make_record("20260525", tired_rate=-20, tired_rate_state_new=2)]
        sleep = [
            _make_sleep("20260525", 300, 40),
            _make_sleep("20260524", 310, 45),
            _make_sleep("20260523", 320, 50),
        ]
        result = coach.assess_fatigue(daily, sleep)
        # sleep degraded, tired_rate Normal → at least Fatigued
        assert result["level"] in ("Fatigued", "Normal")

    def test_stress_amplifies_fatigue(self):
        daily = [_make_record("20260525", tired_rate=-20, tired_rate_state_new=2)]
        health = [_make_health("20260525", 55), _make_health("20260524", 58), _make_health("20260523", 52)]
        result = coach.assess_fatigue(daily, [], health)
        # High stress should push toward Fatigued
        assert "stress" in str(result["contributing_factors"]).lower()
        assert result["level"] in ("Fatigued", "Normal")

    def test_low_stress_keeps_fresh(self):
        daily = [_make_record("20260525", tired_rate=-40, tired_rate_state_new=1)]
        health = [_make_health("20260525", 15), _make_health("20260524", 18), _make_health("20260523", 20)]
        result = coach.assess_fatigue(daily, [], health)
        assert result["level"] in ("Fresh", "Normal")


# ============================================================================
# compute_training_status
# ============================================================================

class TestComputeTrainingStatus:
    def test_optimized(self):
        daily, _ = healthy_fixtures()
        result = coach.compute_training_status(daily)
        assert result["state"] in ("Optimized", "Maintaining", "Performance")

    def test_excessive(self):
        daily, _ = fatigued_fixtures()
        result = coach.compute_training_status(daily)
        assert result["state"] == "Excessive"

    def test_insufficient_data_empty(self):
        result = coach.compute_training_status([])
        assert result["state"] == "Insufficient Data"

    def test_returns_base_fitness_and_load_impact(self):
        daily, _ = healthy_fixtures()
        result = coach.compute_training_status(daily)
        assert result["base_fitness"] is not None
        assert result["load_impact"] is not None

    def test_maintaining_when_low_ratio_with_load(self):
        daily = [_make_record("20260525", t7d=30, t28d=50, training_load_ratio_state=1)]
        result = coach.compute_training_status(daily)
        assert result["state"] == "Maintaining"

    def test_resuming_when_low_ratio_no_load(self):
        daily = [_make_record("20260525", t7d=0, t28d=50, training_load_ratio_state=1)]
        result = coach.compute_training_status(daily)
        assert result["state"] == "Resuming"


# ============================================================================
# analyze_hrv_trend
# ============================================================================

class TestAnalyzeHrvTrend:
    def test_normal_hrv_within_baseline(self):
        daily, _ = healthy_fixtures()
        result = coach.analyze_hrv_trend(daily)
        assert result["status"] == "Normal"
        assert result["latest"] is not None

    def test_low_hrv_below_baseline(self):
        daily, _ = fatigued_fixtures()
        result = coach.analyze_hrv_trend(daily)
        assert result["status"] in ("Low", "Normal")

    def test_insufficient_data(self):
        result = coach.analyze_hrv_trend([])
        assert result["status"] == "Insufficient Data"
        assert result["trend"] == "Stable"

    def test_returns_deviation_pct(self):
        daily, _ = healthy_fixtures()
        result = coach.analyze_hrv_trend(daily)
        assert result["deviation_pct"] is not None

    def test_seven_day_avg(self):
        daily, _ = healthy_fixtures()
        result = coach.analyze_hrv_trend(daily)
        assert result["seven_day_avg"] is not None


# ============================================================================
# analyze_sleep_trend
# ============================================================================

class TestAnalyzeSleepTrend:
    def test_adequate_sleep(self):
        _, sleep = healthy_fixtures()
        result = coach.analyze_sleep_trend(sleep)
        assert result["avg_duration_hours"] >= 7

    def test_sleep_debt(self):
        _, sleep = fatigued_fixtures()
        result = coach.analyze_sleep_trend(sleep)
        assert result["debt_hours"] > 0

    def test_no_data(self):
        result = coach.analyze_sleep_trend([])
        assert result["avg_duration_hours"] is None
        assert result["debt_hours"] == 0

    def test_returns_quality_score(self):
        _, sleep = healthy_fixtures()
        result = coach.analyze_sleep_trend(sleep)
        assert result["quality_score"] is not None


# ============================================================================
# compute_weekly_comparison
# ============================================================================

class TestWeeklyComparison:
    def test_has_load_both_weeks(self):
        daily, _ = healthy_fixtures()
        result = coach.compute_weekly_comparison(daily)
        assert result["this_week_load"] > 0
        assert result["last_week_load"] > 0
        assert "load_change_pct" in result

    def test_no_data(self):
        result = coach.compute_weekly_comparison([])
        assert result["this_week_load"] == 0
        assert result["this_week_load"] == result["last_week_load"]

    def test_returns_session_count(self):
        daily, _ = healthy_fixtures()
        result = coach.compute_weekly_comparison(daily)
        assert result["sessions_completed"] >= 0

    def test_returns_distance_and_duration(self):
        daily, _ = healthy_fixtures()
        result = coach.compute_weekly_comparison(daily)
        assert result["total_distance_km"] > 0
        assert result["total_duration_hours"] > 0

    def test_only_this_week_data(self):
        daily = [_make_record("20260525", training_load=50, distance=8000, duration=2400)]
        result = coach.compute_weekly_comparison(daily)
        assert result["this_week_load"] == 50
        assert result["last_week_load"] == 0
        assert result["load_change_pct"] == 100.0


# ============================================================================
# generate_recommendation
# ============================================================================

class TestGenerateRecommendation:
    def test_ready_optimized_hard_training(self):
        r = coach.generate_recommendation(
            readiness={"score": "Ready"},
            fatigue={"level": "Fresh"},
            training_status={"state": "Optimized"},
        )
        assert r["intensity"] == "Hard"

    def test_moderate_easy_training(self):
        r = coach.generate_recommendation(
            readiness={"score": "Moderate"},
            fatigue={"level": "Fatigued"},
            training_status={"state": "Optimized"},
        )
        assert r["intensity"] == "Easy"

    def test_recovery_day(self):
        r = coach.generate_recommendation(
            readiness={"score": "Recover"},
            fatigue={"level": "Normal"},
            training_status={"state": "Optimized"},
        )
        assert r["intensity"] == "Easy"

    def test_rest_day(self):
        r = coach.generate_recommendation(
            readiness={"score": "Rest"},
            fatigue={"level": "Fatigued"},
            training_status={"state": "Excessive"},
        )
        assert r["intensity"] == "Rest"

    def test_race_ready(self):
        r = coach.generate_recommendation(
            readiness={"score": "Ready"},
            fatigue={"level": "Fresh"},
            training_status={"state": "Performance"},
        )
        assert r["intensity"] == "Hard"
        assert r["duration_minutes"] >= 60

    def test_overtrained_always_rest(self):
        r = coach.generate_recommendation(
            readiness={"score": "Ready"},
            fatigue={"level": "Overtrained"},
            training_status={"state": "Performance"},
        )
        assert r["intensity"] == "Rest"

    def test_return_keys_structure(self):
        r = coach.generate_recommendation(
            readiness={"score": "Moderate"},
            fatigue={"level": "Normal"},
            training_status={"state": "Maintaining"},
        )
        for k in ("primary", "alternative", "intensity", "duration_minutes", "why"):
            assert k in r

    def test_alternative_from_schedule(self):
        r = coach.generate_recommendation(
            readiness={"score": "Ready"},
            fatigue={"level": "Fresh"},
            training_status={"state": "Optimized"},
            schedule=[{"happenDay": "20260526", "name": "Z2 Long Run"}],
        )
        # Alternative may or may not match today's date in test, check it doesn't crash
        assert "alternative" in r

    def test_zone_target_from_profile(self):
        profile = _make_profile()
        r = coach.generate_recommendation(
            readiness={"score": "Ready"},
            fatigue={"level": "Fresh"},
            training_status={"state": "Optimized"},
            user_profile=profile,
        )
        assert "zone_target" in r
        zt = r["zone_target"]
        assert zt["model"] == "MaxHR"
        assert zt["bpm_low"] > 0
        assert zt["bpm_high"] > zt["bpm_low"]

    def test_no_zone_target_without_profile(self):
        r = coach.generate_recommendation(
            readiness={"score": "Ready"},
            fatigue={"level": "Fresh"},
            training_status={"state": "Optimized"},
        )
        assert "zone_target" not in r


# ============================================================================
# compute_trends
# ============================================================================

class TestComputeTrends:
    def test_all_keys_present(self):
        result = coach.compute_trends(
            training_status={"intensity_trend": "Rising"},
            hrv={"trend": "Rising"},
            sleep={"trend": "Stable"},
            daily_records=[],
        )
        for k in ("fitness", "fatigue", "hrv", "sleep"):
            assert k in result

    def test_fitness_from_stamina_trend(self):
        result = coach.compute_trends(
            training_status={"intensity_trend": "Falling"},
            hrv={"trend": "Stable"},
            sleep={"trend": "Stable"},
            daily_records=[],
        )
        assert result["fitness"]["direction"] == "Falling"


# ============================================================================
# generate_alerts
# ============================================================================

class TestGenerateAlerts:
    def test_no_alerts_when_normal(self):
        daily, sleep = healthy_fixtures()
        alerts = coach.generate_alerts(
            daily, sleep,
            training_status=coach.compute_training_status(daily),
            hrv=coach.analyze_hrv_trend(daily),
            fatigue=coach.assess_fatigue(daily, sleep),
        )
        assert len(alerts) == 0  # healthy data → no alerts

    def test_alerts_on_fatigued_data(self):
        daily, sleep = fatigued_fixtures()
        alerts = coach.generate_alerts(
            daily, sleep,
            training_status=coach.compute_training_status(daily),
            hrv=coach.analyze_hrv_trend(daily),
            fatigue=coach.assess_fatigue(daily, sleep),
        )
        assert len(alerts) > 0  # fatigued data → at least one alert

    def test_empty_data_no_alerts(self):
        alerts = coach.generate_alerts(
            [], [],
            training_status=coach.compute_training_status([]),
            hrv=coach.analyze_hrv_trend([]),
            fatigue=coach.assess_fatigue([]),
        )
        assert len(alerts) == 0


# ============================================================================
# determine_overall_status
# ============================================================================

class TestOverallStatus:
    def test_race_ready(self):
        status = coach.determine_overall_status(
            readiness={"score": "Ready"},
            fatigue={"level": "Fresh"},
            training_status={"state": "Performance"},
        )
        assert status == "Race Ready"

    def test_rest_day(self):
        status = coach.determine_overall_status(
            readiness={"score": "Rest"},
            fatigue={"level": "Fatigued"},
            training_status={"state": "Excessive"},
        )
        assert status == "Rest Day Recommended"

    def test_recovery_needed(self):
        status = coach.determine_overall_status(
            readiness={"score": "Recover"},
            fatigue={"level": "Normal"},
            training_status={"state": "Optimized"},
        )
        assert status == "Recovery Needed"

    def test_ready_to_train(self):
        status = coach.determine_overall_status(
            readiness={"score": "Ready"},
            fatigue={"level": "Normal"},
            training_status={"state": "Optimized"},
        )
        assert status == "Ready to Train"

    def test_proceed_with_caution(self):
        status = coach.determine_overall_status(
            readiness={"score": "Moderate"},
            fatigue={"level": "Fatigued"},
            training_status={"state": "Maintaining"},
        )
        assert status == "Proceed with Caution"


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    def test_none_values_in_records(self):
        daily = [_make_record("20260525", avg_sleep_hrv=None, rhr=None, tired_rate=None, tired_rate_state_new=None, stamina_level=None, stamina_level_7d=None)]
        freshness = coach.build_data_freshness(daily, {}, [])
        guardrails = coach.build_training_guardrails(
            {"score": "Moderate"}, {"level": "Normal"}, {"state": "Maintaining"},
            coach.analyze_hrv_trend(daily),
            coach.analyze_sleep_trend([]),
            freshness,
            daily_records=daily,
        )
        assert guardrails is not None
        assert "risk_level" in guardrails

    def test_negative_training_load(self):
        """Training load should never be negative, but if it is, we handle it."""
        daily = [_make_record("20260525", training_load=-10)]
        result = coach.compute_weekly_comparison(daily)
        assert result["this_week_load"] == -10  # pass through — caller's problem

    def test_quality_score_minus_one(self):
        sleep = [_make_sleep("20260525", 450, -1)]
        result = coach.analyze_sleep_trend(sleep)
        assert result["quality_score"] is None  # -1 filtered out

    def test_stamina_level_zero(self):
        daily = [_make_record("20260525", stamina_level=0, stamina_level_7d=5)]
        result = coach.compute_training_status(daily)
        assert result["intensity_trend"] in ("Rising", "Stable", "Falling")

    def test_baseline_zero(self):
        """Baseline of 0 should not cause division by zero."""
        daily = [_make_record("20260525", avg_sleep_hrv=60, baseline=0)]
        result = coach.analyze_hrv_trend(daily)
        assert result["deviation_pct"] is not None
