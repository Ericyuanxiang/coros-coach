"""Tests for coach/ package — safety + efficiency (the unique-value modules)."""

import pytest
import coach


# ============================================================================
# generate_alerts (safety)
# ============================================================================

class TestGenerateAlerts:
    def test_no_alerts_when_normal(self):
        alerts = coach.generate_alerts(
            [], [],
            training_status={"state": "Optimized", "load_impact": 0.8},
            hrv={"status": "Normal"},
            fatigue={"level": "Fresh"},
        )
        assert len(alerts) == 0

    def test_alerts_on_overtrained(self):
        alerts = coach.generate_alerts(
            [], [],
            training_status={"state": "Excessive", "load_impact": 1.5},
            hrv={"status": "Low"},
            fatigue={"level": "Overtrained"},
        )
        assert len(alerts) > 0

    def test_empty_data_no_alerts(self):
        alerts = coach.generate_alerts(
            [], [],
            training_status={"state": "Insufficient Data", "load_impact": 0},
            hrv={"status": "Insufficient Data"},
            fatigue={"level": "Normal"},
        )
        assert len(alerts) == 0

    def test_hrv_streak_triggers_alert(self):
        daily = [
            {"avg_sleep_hrv": 50, "baseline": 65, "date": "20260529"},
            {"avg_sleep_hrv": 50, "baseline": 65, "date": "20260528"},
            {"avg_sleep_hrv": 50, "baseline": 65, "date": "20260527"},
        ]
        alerts = coach.generate_alerts(
            daily, [],
            training_status={"state": "Optimized", "load_impact": 0.8},
            hrv={"status": "Low"},
            fatigue={"level": "Normal"},
        )
        assert any("HRV" in a for a in alerts)


# ============================================================================
# analyse_efficiency (efficiency)
# ============================================================================

class TestAnalyseEfficiency:
    def test_insufficient_data(self):
        result = coach.analyse_efficiency([])
        assert result["trend"] == "Insufficient data"

    def test_two_runs_similar_pace_improving(self):
        runs = [
            {"sport_type": 100, "start_time": "20260501", "avg_hr": 160,
             "distance_meters": 5000, "duration_seconds": 1500},       # pace 5:00, HR 160
            {"sport_type": 100, "start_time": "20260515", "avg_hr": 155,
             "distance_meters": 5000, "duration_seconds": 1500},       # same pace, HR -5
        ]
        result = coach.analyse_efficiency(runs)
        assert result["trend"] == "improving"
        assert result["total_pairs"] == 1

    def test_two_runs_similar_pace_declining(self):
        runs = [
            {"sport_type": 100, "start_time": "20260501", "avg_hr": 150,
             "distance_meters": 5000, "duration_seconds": 1500},
            {"sport_type": 100, "start_time": "20260515", "avg_hr": 158,
             "distance_meters": 5000, "duration_seconds": 1500},
        ]
        result = coach.analyse_efficiency(runs)
        assert result["trend"] == "declining"

    def test_non_running_filtered_out(self):
        runs = [
            {"sport_type": 200, "start_time": "20260501", "avg_hr": 140,
             "distance_meters": 20000, "duration_seconds": 3600},  # cycling
        ]
        result = coach.analyse_efficiency(runs)
        assert result["trend"] == "Insufficient data"


# ============================================================================
# analyse_pace_at_hr (efficiency)
# ============================================================================

class TestAnalysePaceAtHR:
    def test_insufficient_data(self):
        result = coach.analyse_pace_at_hr([], 150)
        assert result["trend"] == "Insufficient data"

    def test_pace_improving_at_hr(self):
        runs = [
            {"sport_type": 100, "start_time": "20260501", "avg_hr": 150,
             "distance_meters": 5000, "duration_seconds": 1500},   # 5:00/km
            {"sport_type": 100, "start_time": "20260508", "avg_hr": 150,
             "distance_meters": 5000, "duration_seconds": 1440},   # 4:48/km (faster)
        ]
        result = coach.analyse_pace_at_hr(runs, 150)
        assert result["trend"] == "improving"
        assert result["sample_count"] == 2
