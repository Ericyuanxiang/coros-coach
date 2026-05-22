"""Unit tests for coros_api parser functions."""

import pytest
from datetime import datetime

# These tests import coros_api internals — they test the parsers, not the API.
import coros_api
from models import DailyRecord, ActivitySummary, SleepRecord, SleepPhases


# ---------------------------------------------------------------------------
# _parse_daily_record
# ---------------------------------------------------------------------------

SAMPLE_DAY_ITEM = {
    "happenDay": 20260515,
    "timestamp": 1772467200,
    "avgSleepHrv": 66.0,
    "sleepHrvBase": 59.0,
    "sleepHrvIntervalList": [5, 24, 41, 77],
    "rhr": 60,
    "testRhr": 58,
    "lthr": 180,
    "trainingLoad": 39,
    "trainingLoadTarget": 0.0,
    "trainingLoadRatio": 0.14,
    "trainingLoadRatioState": 1,
    "trainingLoadRatioZoneList": [
        {"max": 0.5, "min": 0.0, "type": 1},
        {"max": 0.8, "min": 0.5, "type": 2},
    ],
    "t7d": 58,
    "t28d": 77,
    "ct7dMaxFixed": 798.0,
    "ct7dMin": 319.2,
    "recomendTlMax": 718.2,
    "recomendTlMin": 399.0,
    "tiredRateNew": -49.0,
    "tiredRate": 6.0,
    "tiredRateStateNew": 1,
    "tiredRateNewZoneList": [
        {"max": -28.5, "min": -57.0, "type": 1},
        {"max": -5.7, "min": -28.5, "type": 2},
    ],
    "tib": 54.0,
    "ati": 8.0,
    "cti": 57.0,
    "performance": 2,
    "distance": 5000.0,
    "distanceTarget": 0.0,
    "duration": 1800,
    "durationTarget": 0,
    "vo2max": 57,
    "staminaLevel": 89.1,
    "staminaLevel7d": 100.0,
    "ltsp": 247,
}


class TestParseDailyRecord:
    def test_parses_all_35_fields(self):
        """Every field in the sample should be captured in DailyRecord."""
        rec = coros_api._parse_daily_record(SAMPLE_DAY_ITEM)
        assert rec.date == "20260515"
        assert rec.timestamp == 1772467200
        assert rec.avg_sleep_hrv == 66.0
        assert rec.baseline == 59.0
        assert rec.interval_list == [5, 24, 41, 77]
        assert rec.rhr == 60
        assert rec.test_rhr == 58
        assert rec.lthr == 180
        assert rec.training_load == 39
        assert rec.training_load_target == 0.0
        assert rec.training_load_ratio == 0.14
        assert rec.training_load_ratio_state == 1
        assert len(rec.training_load_ratio_zone_list) == 2
        assert rec.t7d == 58
        assert rec.t28d == 77
        assert rec.ct7d_max_fixed == 798.0
        assert rec.ct7d_min == 319.2
        assert rec.recomend_tl_max == 718.2
        assert rec.recomend_tl_min == 399.0
        assert rec.tired_rate == -49.0
        assert rec.tired_rate_old == 6.0
        assert rec.tired_rate_state_new == 1
        assert len(rec.tired_rate_new_zone_list) == 2
        assert rec.tib == 54.0
        assert rec.ati == 8.0
        assert rec.cti == 57.0
        assert rec.performance == 2
        assert rec.distance == 5000.0
        assert rec.distance_target == 0.0
        assert rec.duration == 1800
        assert rec.duration_target == 0
        assert rec.vo2max == 57
        assert rec.stamina_level == 89.1
        assert rec.stamina_level_7d == 100.0
        assert rec.ltsp == 247

    def test_handles_missing_fields_gracefully(self):
        """Sparse item with only happenDay should not raise."""
        rec = coros_api._parse_daily_record({"happenDay": 20260501})
        assert rec.date == "20260501"
        assert rec.vo2max is None
        assert rec.training_load is None
        assert rec.tired_rate_new_zone_list is None

    def test_date_is_always_string(self):
        """happenDay can be int or str — output must be str."""
        r1 = coros_api._parse_daily_record({"happenDay": 20260501})
        r2 = coros_api._parse_daily_record({"happenDay": "20260501"})
        assert isinstance(r1.date, str)
        assert isinstance(r2.date, str)

    def test_model_dump_includes_all_fields(self):
        """model_dump() must include all 35 fields (None for missing)."""
        rec = coros_api._parse_daily_record(SAMPLE_DAY_ITEM)
        dumped = rec.model_dump()
        assert len(dumped) == 35, f"Expected 35, got {len(dumped)}"
        assert "recomend_tl_max" in dumped
        assert "training_load_ratio_state" in dumped
        assert "tired_rate_new_zone_list" in dumped

    def test_performance_negative_one_means_no_data(self):
        rec = coros_api._parse_daily_record({"happenDay": 20260501, "performance": -1})
        assert rec.performance == -1

    def test_zone_lists_preserved_as_dicts(self):
        rec = coros_api._parse_daily_record(SAMPLE_DAY_ITEM)
        zone = rec.training_load_ratio_zone_list[0]
        assert isinstance(zone, dict)
        assert zone["type"] == 1
        assert "max" in zone and "min" in zone


# ---------------------------------------------------------------------------
# _parse_activity
# ---------------------------------------------------------------------------

SAMPLE_ACTIVITY = {
    "labelId": 123456789,
    "name": None,
    "remark": "Morning Run",
    "sportType": 100,
    "startTime": "1772467200",
    "endTime": "1772469000",
    "totalTime": 1800,
    "distance": 5000.0,
    "totalDistance": None,
    "avgHr": 152,
    "maxHr": 172,
    "calories": 320,
    "trainingLoad": 45,
    "avgPower": None,
    "avgCadence": 175,
    "elevationGain": 25,
}


class TestParseActivity:
    def test_parses_basic_fields(self):
        act = coros_api._parse_activity(SAMPLE_ACTIVITY)
        assert act.activity_id == "123456789"
        assert act.name == "Morning Run"
        assert act.sport_type == 100
        assert act.sport_name == "Running"
        assert act.duration_seconds == 1800
        assert act.distance_meters == 5000.0
        assert act.avg_hr == 152
        assert act.max_hr == 172

    def test_sport_name_unknown_type(self):
        act = coros_api._parse_activity({**SAMPLE_ACTIVITY, "sportType": 9999})
        assert act.sport_name == "Sport 9999"

    def test_sport_name_none_type(self):
        act = coros_api._parse_activity({**SAMPLE_ACTIVITY, "sportType": None})
        assert act.sport_name is None

    def test_falls_back_to_remark_when_name_none(self):
        act = coros_api._parse_activity({
            "labelId": 1, "name": None, "remark": "Evening Jog", "sportType": 100,
        })
        assert act.name == "Evening Jog"

    def test_prefers_totalDistance_when_distance_none(self):
        act = coros_api._parse_activity({
            "labelId": 1, "sportType": 100,
            "distance": None, "totalDistance": 10000.0,
        })
        assert act.distance_meters == 10000.0


# ---------------------------------------------------------------------------
# _parse_workout
# ---------------------------------------------------------------------------

SAMPLE_WORKOUT = {
    "id": "477570944710393956",
    "name": "Interval Session",
    "sportType": 1,
    "estimatedTime": 2700,
    "estimatedDistance": 800000,
    "exerciseNum": 3,
    "trainingLoad": 55,
    "createTimestamp": 1779090407,
    "exercises": [
        {
            "name": "Warm-up",
            "targetValue": 600,
            "intensityValue": 130,
            "intensityValueExtend": 150,
            "intensityType": 2,
            "hrType": 2,
            "intensityPercent": 58000,
            "intensityPercentExtend": 74000,
            "overview": "sid_run_training",
            "restValue": 0,
            "sortNo": 0,
            "sets": 1,
        },
        {
            "name": "Intervals",
            "targetValue": 180,
            "intensityValue": 160,
            "intensityValueExtend": 172,
            "intensityType": 2,
            "hrType": 2,
            "intensityPercent": 80000,
            "intensityPercentExtend": 95000,
            "overview": "sid_run_training",
            "restValue": 120,
            "sortNo": 1,
            "sets": 5,
        },
    ],
}


class TestParseWorkout:
    def test_parses_top_level_workout(self):
        w = coros_api._parse_workout(SAMPLE_WORKOUT)
        assert w["id"] == "477570944710393956"
        assert w["name"] == "Interval Session"
        assert w["sport_type"] == 1
        assert w["estimated_time_seconds"] == 2700
        assert w["estimated_distance"] == 800000
        assert w["training_load"] == 55
        assert w["create_timestamp"] == 1779090407
        assert w["exercise_count"] == 3

    def test_parses_exercise_basics(self):
        ex = coros_api._parse_workout(SAMPLE_WORKOUT)["exercises"][0]
        assert ex["name"] == "Warm-up"
        assert ex["duration_seconds"] == 600
        assert ex["power_low_w"] == 130
        assert ex["power_high_w"] == 150
        assert ex["sets"] == 1

    def test_parses_exercise_hrmeta(self):
        ex = coros_api._parse_workout(SAMPLE_WORKOUT)["exercises"][0]
        assert ex["intensity_type"] == 2
        assert ex["hr_type"] == 2
        assert ex["intensity_percent"] == 58000
        assert ex["intensity_percent_extend"] == 74000
        assert ex["overview"] == "sid_run_training"
        assert ex["rest_seconds"] == 0
        assert ex["sort_no"] == 0

    def test_second_exercise_has_rest(self):
        ex = coros_api._parse_workout(SAMPLE_WORKOUT)["exercises"][1]
        assert ex["name"] == "Intervals"
        assert ex["rest_seconds"] == 120
        assert ex["sets"] == 5

    def test_handles_empty_exercises(self):
        w = coros_api._parse_workout({**SAMPLE_WORKOUT, "exercises": [], "exerciseNum": 0})
        assert w["exercises"] == []
        assert w["exercise_count"] == 0

    def test_handles_minimal_workout(self):
        w = coros_api._parse_workout({"id": "1", "exercises": []})
        assert w["id"] == "1"
        assert w["name"] is None
        assert w["exercises"] == []


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestModels:
    def test_daily_record_model_creation(self):
        rec = DailyRecord(date="20260515", rhr=60, training_load=39)
        assert rec.date == "20260515"
        assert rec.rhr == 60
        assert rec.vo2max is None

    def test_daily_record_defaults_to_none(self):
        rec = DailyRecord(date="20260501")
        assert rec.rhr is None
        assert rec.performance is None
        assert rec.training_load_ratio_state is None

    def test_activity_summary_model(self):
        act = ActivitySummary(activity_id="123", sport_type=100, sport_name="Running")
        assert act.activity_id == "123"
        assert act.name is None

    def test_sleep_record_model(self):
        phases = SleepPhases(deep_minutes=80, light_minutes=200, rem_minutes=100, awake_minutes=10)
        rec = SleepRecord(date="20260515", total_duration_minutes=390, phases=phases, avg_hr=58)
        assert rec.phases.deep_minutes == 80
        assert rec.avg_hr == 58
        assert rec.quality_score is None

    def test_daily_record_has_all_categories(self):
        """Sanity-check that the 35 fields are organized by category."""
        fields = DailyRecord.model_fields
        # Core
        assert "date" in fields
        assert "timestamp" in fields
        # HRV
        assert "avg_sleep_hrv" in fields
        assert "baseline" in fields
        assert "interval_list" in fields
        # HR
        assert "rhr" in fields
        assert "test_rhr" in fields
        assert "lthr" in fields
        # Training load
        assert "training_load" in fields
        assert "training_load_target" in fields
        assert "training_load_ratio_state" in fields
        assert "recomend_tl_max" in fields
        # Fatigue
        assert "tired_rate" in fields
        assert "tired_rate_state_new" in fields
        assert "tired_rate_new_zone_list" in fields
        # Performance
        assert "ati" in fields
        assert "cti" in fields
        assert "performance" in fields
        # Volume
        assert "distance" in fields
        assert "duration" in fields
        # Fitness
        assert "vo2max" in fields
        assert "stamina_level" in fields
        assert "ltsp" in fields


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_parse_daily_empty_dict(self):
        rec = coros_api._parse_daily_record({})
        assert rec.date == ""
        assert rec.vo2max is None

    def test_parse_activity_minimal(self):
        act = coros_api._parse_activity({"labelId": "1"})
        assert act.activity_id == "1"
        assert act.sport_type is None
        assert act.name is None

    def test_large_values(self):
        """Large integers/floats should not overflow."""
        rec = coros_api._parse_daily_record({
            "happenDay": 20260501,
            "distance": 42195.0,
            "duration": 86400,
            "vo2max": 85,
            "trainingLoad": 999,
            "t7d": 9999,
            "t28d": 99999,
        })
        assert rec.distance == 42195.0
        assert rec.vo2max == 85

    def test_negative_tired_rate(self):
        """tiredRateNew can be negative (fresh)."""
        rec = coros_api._parse_daily_record({
            "happenDay": 20260501, "tiredRateNew": -65.0,
        })
        assert rec.tired_rate == -65.0

    def test_null_intensity_fields_in_exercise(self):
        """Exercise with missing intensity fields should not crash."""
        w = coros_api._parse_workout({
            "id": "1",
            "exercises": [{"name": "Rest", "targetValue": 60}],
        })
        ex = w["exercises"][0]
        assert ex["intensity_type"] is None
        assert ex["hr_type"] is None
        assert ex["overview"] is None
