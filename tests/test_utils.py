"""Unit tests for coros_api utility functions and server helpers."""

import pytest
import httpx

import coros_api
from server import _summarize_steps, _tool_error


# ============================================================================
# _check_response
# ============================================================================

class TestCheckResponse:
    def test_success_result_passes(self):
        coros_api._check_response({"result": "0000"}, "test op")

    def test_non_zero_result_raises_value_error(self):
        with pytest.raises(ValueError, match="Coros test op error:"):
            coros_api._check_response({"result": "1001", "message": "bad token"}, "test op")

    def test_error_without_message(self):
        with pytest.raises(ValueError, match="unknown error"):
            coros_api._check_response({"result": "9999"}, "login")


# ============================================================================
# _md5
# ============================================================================

class TestMd5:
    def test_known_hash(self):
        assert coros_api._md5("hello") == "5d41402abc4b2a76b9719d911017c592"

    def test_empty_string(self):
        assert coros_api._md5("") == "d41d8cd98f00b204e9800998ecf8427e"

    def test_consistent_output(self):
        assert coros_api._md5("coros") == coros_api._md5("coros")


# ============================================================================
# _base_url
# ============================================================================

class TestBaseUrl:
    def test_eu_region(self):
        assert coros_api._base_url("eu") == "https://teameuapi.coros.com"

    def test_us_region(self):
        assert coros_api._base_url("us") == "https://teamapi.coros.com"

    def test_cn_region(self):
        assert coros_api._base_url("cn") == "https://teamcnapi.coros.com"

    def test_unknown_falls_back_to_eu(self):
        assert coros_api._base_url("xyz") == "https://teameuapi.coros.com"


# ============================================================================
# _pace_sec_per_km_to_mmss0
# ============================================================================

class TestPaceConversion:
    def test_four_forty_three(self):
        assert coros_api._pace_sec_per_km_to_mmss0(283) == 44300

    def test_exact_minutes(self):
        assert coros_api._pace_sec_per_km_to_mmss0(300) == 50000

    def test_sub_four(self):
        assert coros_api._pace_sec_per_km_to_mmss0(239) == 35900

    def test_slow_pace(self):
        assert coros_api._pace_sec_per_km_to_mmss0(420) == 70000


# ============================================================================
# _is_zone_mode
# ============================================================================

ZONE_TABLE = [
    {"hr": 120, "ratio": 59.0},
    {"hr": 140, "ratio": 74.0},
    {"hr": 155, "ratio": 84.0},
    {"hr": 165, "ratio": 88.0},
    {"hr": 175, "ratio": 95.0},
    {"hr": 185, "ratio": 100.0},
]


class TestIsZoneMode:
    def test_zone_detected_in_plain_steps(self):
        assert coros_api._is_zone_mode([
            {"name": "warmup", "duration_minutes": 10, "hr_low": 1}
        ])

    def test_zone_detected_in_repeat_group(self):
        assert coros_api._is_zone_mode([
            {"repeat": 3, "steps": [
                {"name": "effort", "duration_minutes": 3, "hr_low": 5}
            ]}
        ])

    def test_absolute_bpm_not_detected_as_zone(self):
        assert not coros_api._is_zone_mode([
            {"name": "effort", "duration_minutes": 10, "hr_low": 140}
        ])

    def test_missing_hr_low_treated_as_bpm(self):
        assert not coros_api._is_zone_mode([
            {"name": "free ride", "duration_minutes": 30}
        ])


# ============================================================================
# _zone_to_bpm
# ============================================================================

class TestZoneToBpm:
    def test_zone_1_from_zero(self):
        low, high = coros_api._zone_to_bpm(1, ZONE_TABLE)
        assert low == 0
        assert high == 120

    def test_zone_2(self):
        low, high = coros_api._zone_to_bpm(2, ZONE_TABLE)
        assert low == 120
        assert high == 140

    def test_zone_6_top(self):
        low, high = coros_api._zone_to_bpm(6, ZONE_TABLE)
        assert low == 175
        assert high == 185


# ============================================================================
# _zone_to_percent
# ============================================================================

class TestZoneToPercent:
    def test_zone_1_from_zero(self):
        low, high = coros_api._zone_to_percent(1, ZONE_TABLE)
        assert low == 0
        assert high == 59000

    def test_zone_2(self):
        low, high = coros_api._zone_to_percent(2, ZONE_TABLE)
        assert low == 59000
        assert high == 74000

    def test_zone_6(self):
        low, high = coros_api._zone_to_percent(6, ZONE_TABLE)
        assert low == 95000
        assert high == 100000


# ============================================================================
# _multiplier_for
# ============================================================================

class TestMultiplierFor:
    def test_hr_type_zero(self):
        assert coros_api._multiplier_for(2) == 0

    def test_pace_type_1000(self):
        assert coros_api._multiplier_for(3) == 1000

    def test_power_type_zero(self):
        assert coros_api._multiplier_for(6) == 0

    def test_cadence_type_zero(self):
        assert coros_api._multiplier_for(7) == 0

    def test_equivalent_pace_type_1000(self):
        assert coros_api._multiplier_for(8) == 1000

    def test_unknown_type_returns_zero(self):
        assert coros_api._multiplier_for(99) == 0


# ============================================================================
# _resolve_intensity
# ============================================================================

class TestResolveIntensity:
    def test_zone_mode_returns_bpm_and_zone_number(self):
        ival, iext, zone_low = coros_api._resolve_intensity(
            {"hr_low": 3}, intensity_type=2, mult=0,
            use_zone=True, zone_table=ZONE_TABLE,
        )
        assert ival == 140   # Z3 low
        assert iext == 155   # Z3 high
        assert zone_low == 3

    def test_bpm_mode_passes_absolute_values(self):
        ival, iext, zone_low = coros_api._resolve_intensity(
            {"hr_low": 130, "hr_high": 150}, intensity_type=2, mult=0,
            use_zone=False, zone_table=ZONE_TABLE,
        )
        assert ival == 130
        assert iext == 150
        assert zone_low is None

    def test_pace_mode_with_pace_low(self):
        ival, iext, zone_low = coros_api._resolve_intensity(
            {"pace_low": 283, "pace_high": 300},
            intensity_type=3, mult=1000, use_zone=False, zone_table=None,
        )
        assert ival == 283000
        assert iext == 300000

    def test_pace_mode_without_pace_high_falls_back(self):
        ival, iext, zone_low = coros_api._resolve_intensity(
            {"pace_low": 300},
            intensity_type=8, mult=1000, use_zone=False, zone_table=None,
        )
        assert ival == 300000
        assert iext == 300000

    def test_bpm_mode_defaults_to_zero(self):
        ival, iext, zone_low = coros_api._resolve_intensity(
            {}, intensity_type=2, mult=0, use_zone=False, zone_table=None,
        )
        assert ival == 0
        assert iext == 0


# ============================================================================
# _drop_keys
# ============================================================================

class TestDropKeys:
    def test_removes_specified_keys(self):
        assert coros_api._drop_keys({"a": 1, "b": 2, "c": 3}, frozenset({"b"})) == {"a": 1, "c": 3}

    def test_empty_keys_is_identity(self):
        assert coros_api._drop_keys({"a": 1}, frozenset()) == {"a": 1}

    def test_all_keys_dropped(self):
        assert coros_api._drop_keys({"a": 1}, frozenset({"a"})) == {}

    def test_returns_new_dict(self):
        d = {"a": 1}
        result = coros_api._drop_keys(d, frozenset())
        assert result is not d


# ============================================================================
# _readable_overview
# ============================================================================

class TestReadableOverview:
    def test_sid_strength_prefix(self):
        assert coros_api._readable_overview("sid_strength_squats") == "Squats"

    def test_sid_run_prefix(self):
        assert coros_api._readable_overview("sid_run_warm_up_dist") == "Warm up dist"

    def test_sid_generic_prefix(self):
        assert coros_api._readable_overview("sid_cycling") == "Cycling"

    def test_no_sid_prefix_passes_through(self):
        assert coros_api._readable_overview("custom_overview_key") == "Custom overview key"


# ============================================================================
# _strip_exercise / _strip_program / _strip_schedule
# ============================================================================

FULL_EXERCISE = {
    "name": "Squats", "overview": "sid_strength_squats", "sortNo": 0,
    "originId": "abc", "intensityCustom": True, "videoUrl": "http://x",
}

FULL_PROGRAM = {
    "name": "Plan A", "exercises": [FULL_EXERCISE],
    "exerciseBarChart": [1, 2, 3], "headPic": "http://img", "userId": "u1",
}

FULL_SCHEDULE = {
    "entities": [{"dayNo": 1, "name": "E1", "sortNo": 0, "userId": "u1"}],
    "programs": [FULL_PROGRAM],
    "sportDatasInPlan": [], "likeTpIds": [],
}


class TestStripFunctions:
    def test_strip_exercise_removes_internal_keys(self):
        clean = coros_api._strip_exercise(FULL_EXERCISE)
        assert "sortNo" not in clean
        assert "originId" not in clean
        assert "videoUrl" not in clean
        assert clean["name"] == "Squats"

    def test_strip_exercise_readable_overview(self):
        clean = coros_api._strip_exercise(FULL_EXERCISE)
        assert clean["overview"] == "Squats"

    def test_strip_program_strips_exercises_recursively(self):
        clean = coros_api._strip_program(FULL_PROGRAM)
        assert "exerciseBarChart" not in clean
        assert "headPic" not in clean
        ex = clean["exercises"][0]
        assert "sortNo" not in ex
        assert ex["overview"] == "Squats"

    def test_strip_program_no_exercises(self):
        prog = {"name": "P", "headPic": "x"}
        clean = coros_api._strip_program(prog)
        assert "headPic" not in clean
        assert "exercises" not in clean

    def test_strip_schedule_top_level(self):
        clean = coros_api._strip_schedule(FULL_SCHEDULE)
        assert "sportDatasInPlan" not in clean
        assert "likeTpIds" not in clean

    def test_strip_schedule_strips_entities(self):
        clean = coros_api._strip_schedule(FULL_SCHEDULE)
        e = clean["entities"][0]
        assert "dayNo" not in e
        assert "sortNo" not in e
        assert "userId" not in e
        assert e["name"] == "E1"

    def test_strip_schedule_strips_programs(self):
        clean = coros_api._strip_schedule(FULL_SCHEDULE)
        prog = clean["programs"][0]
        assert "exerciseBarChart" not in prog
        ex = prog["exercises"][0]
        assert ex["overview"] == "Squats"


# ============================================================================
# _build_power_exercise
# ============================================================================

class TestBuildPowerExercise:
    def test_basic_build(self):
        ex = coros_api._build_power_exercise(
            ex_id=1, name="Warmup", sport_type=2,
            power_low=148, power_high=192,
            target_value=600, sort_no=16777216, group_id="0",
        )
        assert ex["id"] == 1
        assert ex["name"] == "Warmup"
        assert ex["sportType"] == 2
        assert ex["intensityType"] == 6
        assert ex["intensityValue"] == 148
        assert ex["intensityValueExtend"] == 192
        assert ex["targetType"] == 2
        assert ex["targetValue"] == 600
        assert ex["isGroup"] is False
        assert ex["groupId"] == "0"

    def test_group_member(self):
        ex = coros_api._build_power_exercise(
            ex_id=5, name="Interval", sport_type=2,
            power_low=265, power_high=285,
            target_value=180, sort_no=16777216 + 65536,
            group_id="3",
        )
        assert ex["groupId"] == "3"
        assert ex["sortNo"] == 16777216 + 65536


# ============================================================================
# _build_run_exercise
# ============================================================================

class TestBuildRunExercise:
    def test_zone_mode_adds_percent_fields(self):
        ex = coros_api._build_run_exercise(
            ex_id=1, name="Z2 Run", sport_type=1,
            intensity_type=2, intensity_value=120, intensity_extend=140,
            target_value=2400, sort_no=16777216,
            group_id="0", mult=0, hr_type=3,
            use_zone=True, zone_low=2, zone_table=ZONE_TABLE,
        )
        assert ex["intensityType"] == 2
        assert ex["hrType"] == 3
        assert ex["isIntensityPercent"] is True
        assert ex["intensityPercent"] == 59000
        assert ex["intensityPercentExtend"] == 74000

    def test_bpm_mode_no_percent_fields(self):
        ex = coros_api._build_run_exercise(
            ex_id=2, name="Tempo", sport_type=1,
            intensity_type=2, intensity_value=155, intensity_extend=165,
            target_value=1200, sort_no=16777216 * 2,
            group_id="0", mult=0, hr_type=3,
            use_zone=False, zone_low=None, zone_table=ZONE_TABLE,
        )
        assert "isIntensityPercent" not in ex
        assert "intensityPercent" not in ex

    def test_pace_type_does_not_set_hr_type(self):
        ex = coros_api._build_run_exercise(
            ex_id=3, name="Pace Run", sport_type=1,
            intensity_type=3, intensity_value=283000, intensity_extend=300000,
            target_value=1800, sort_no=16777216 * 3,
            group_id="0", mult=1000, hr_type=3,
            use_zone=False, zone_low=None, zone_table=None,
        )
        assert "hrType" not in ex
        assert "isIntensityPercent" not in ex

    def test_returns_new_dict_each_call(self):
        ex1 = coros_api._build_run_exercise(
            ex_id=1, name="A", sport_type=1,
            intensity_type=2, intensity_value=100, intensity_extend=120,
            target_value=600, sort_no=1,
            group_id="0", mult=0, hr_type=1,
            use_zone=False, zone_low=None, zone_table=None,
        )
        ex2 = coros_api._build_run_exercise(
            ex_id=2, name="B", sport_type=1,
            intensity_type=2, intensity_value=100, intensity_extend=120,
            target_value=600, sort_no=1,
            group_id="0", mult=0, hr_type=1,
            use_zone=False, zone_low=None, zone_table=None,
        )
        assert ex1 is not ex2  # immutability: each call returns new dict


# ============================================================================
# _summarize_steps (from server.py)
# ============================================================================

class TestSummarizeSteps:
    def test_plain_steps(self):
        steps = [
            {"name": "Warm-up", "duration_minutes": 10},
            {"name": "Main set", "duration_minutes": 40},
            {"name": "Cool-down", "duration_minutes": 10},
        ]
        total, count = _summarize_steps(steps)
        assert total == 60.0
        assert count == 3

    def test_with_repeat_group(self):
        steps = [
            {"name": "Warm-up", "duration_minutes": 15},
            {"repeat": 5, "steps": [
                {"name": "VO2max", "duration_minutes": 3},
                {"name": "Recovery", "duration_minutes": 3},
            ]},
            {"name": "Cool-down", "duration_minutes": 10},
        ]
        total, count = _summarize_steps(steps)
        # 15 + 5*(3+3) + 10 = 55
        assert total == 55.0
        # 1 plain + (1 group + 2 sub) + 1 plain = 5
        assert count == 5

    def test_empty_steps(self):
        total, count = _summarize_steps([])
        assert total == 0.0
        assert count == 0


# ============================================================================
# _tool_error (from server.py)
# ============================================================================

class TestToolError:
    def test_http_status_error(self):
        resp = httpx.Response(401, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("unauthorized", request=resp.request, response=resp)
        result = _tool_error(exc)
        assert result["error_type"] == "http"
        assert "401" in result["error"]

    def test_connect_error(self):
        exc = httpx.ConnectError("connection refused")
        result = _tool_error(exc)
        assert result["error_type"] == "network"

    def test_timeout(self):
        exc = httpx.TimeoutException("timed out")
        result = _tool_error(exc, timeout=30)
        assert result["error_type"] == "timeout"
        assert result["timeout"] == 30

    def test_value_error(self):
        result = _tool_error(ValueError("bad token"))
        assert result["error_type"] == "api_error"
        assert result["error"] == "bad token"

    def test_unexpected_error(self):
        result = _tool_error(RuntimeError("boom"))
        assert result["error_type"] == "internal"
        assert "boom" in result["error"]

    def test_passes_extra_kwargs(self):
        result = _tool_error(ValueError("x"), authenticated=False, records=[])
        assert result["authenticated"] is False
        assert result["records"] == []
