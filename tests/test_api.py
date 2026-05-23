"""Integration tests for the most fragile coros_api HTTP functions.

Covers the functions with the most complex internal logic — dual-endpoint
merge, SSR scraping + pagination, and GET→POST chains.  Simple single-GET
functions (dashboard, delete, schedule, user_profile) are excluded because
they add boilerplate without meaningful protection.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from coros_api import (
    _check_response,
    fetch_training_analysis,
    fetch_training_library,
    import_training_program,
)
from models import StoredAuth


def make_auth(region: str = "cn") -> StoredAuth:
    return StoredAuth(
        access_token="test-token-abc",
        user_id="4647526",
        region=region,
        timestamp=1700000000000,
    )


SUCCESS = {"result": "0000", "data": {}}
API_ERROR = {"result": "1001", "message": "invalid token"}


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

class MockResponse:
    def __init__(self, json_body=None, text=""):
        self._json = json_body or {}
        self.text = text
        self.status_code = 200

    def json(self):
        return self._json

    def raise_for_status(self):
        pass

    class headers:
        @staticmethod
        def get_list(_):
            return []


class MockClient:
    def __init__(self, get_resp=None, post_resp=None, error=None):
        self._get_resp = get_resp
        self._post_resp = post_resp
        self._error = error

    async def get(self, *args, **kwargs):
        if self._error:
            raise self._error
        if callable(self._get_resp):
            return self._get_resp(*args, **kwargs)
        return self._get_resp

    async def post(self, *args, **kwargs):
        if self._error:
            raise self._error
        if callable(self._post_resp):
            return self._post_resp(*args, **kwargs)
        return self._post_resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _resp(json_body=None, text=""):
    return MockResponse(json_body=json_body, text=text)


def _patch_http(get_resp=None, post_resp=None, error=None):
    return patch("httpx.AsyncClient",
                 return_value=MockClient(get_resp, post_resp, error))


# ---------------------------------------------------------------------------
# _check_response
# ---------------------------------------------------------------------------

class TestCheckResponse:
    def test_passes_on_result_0000(self):
        _check_response({"result": "0000"}, "dummy")

    def test_raises_on_error_result(self):
        with pytest.raises(ValueError, match="Coros dummy error: bad"):
            _check_response({"result": "9999", "message": "bad"}, "dummy")


# ---------------------------------------------------------------------------
# fetch_training_analysis — dual parallel API, merge logic
# ---------------------------------------------------------------------------

DAY_ITEM = {
    "happenDay": 20260515, "timestamp": 1772467200,
    "avgSleepHrv": 66.0, "sleepHrvBase": 59.0, "sleepHrvIntervalList": [5, 24, 41, 77],
    "rhr": 60, "testRhr": 58, "lthr": 180,
    "trainingLoad": 39, "trainingLoadTarget": 0.0, "trainingLoadRatio": 0.14,
    "trainingLoadRatioState": 1,
    "trainingLoadRatioZoneList": [{"max": 0.5, "min": 0.0, "type": 1}],
    "t7d": 280, "t28d": 1120, "ct7dMaxFixed": 320.0, "ct7dMin": 200.0,
    "recomendTlMax": 400.0, "recomendTlMin": 250.0,
    "tiredRate": 2.0, "tiredRateOld": 1.8,
    "tiredRateStateNew": 0, "tiredRateNewZoneList": [],
    "tib": 1.0, "ati": 30.0, "cti": 28.0, "performance": 5,
    "distance": 5000.0, "distanceTarget": 6000.0,
    "duration": 1800, "durationTarget": 2000,
    "vo2max": 52, "staminaLevel": 45.0, "staminaLevel7d": 44.0, "ltsp": 253,
    "preTiredRate": 0.0, "weekHrvAvg": 0.0,
}


def _analysis_side_effect(url, **kwargs):
    if "dayDetail" in url:
        return _resp({"result": "0000", "data": {"dayList": [DAY_ITEM]}})
    return _resp({
        "result": "0000",
        "data": {
            "t7dayList": [],
            "weekList": [{"firstDayOfWeek": "20260512", "trainingLoad": 200}],
            "record": {}, "sportStatistic": [], "summaryInfo": {},
            "tlIntensity": {}, "sportDataSummary": {"totalActivityCount": 42},
            "trainingWeekStageList": [],
        },
    })


class TestFetchTrainingAnalysis:
    @pytest.mark.asyncio
    async def test_returns_all_8_panels(self):
        auth = make_auth()
        with _patch_http(get_resp=_analysis_side_effect):
            result = await fetch_training_analysis(auth, "20260515", "20260522")

        for key in ("daily_records", "week_list", "records", "sport_statistic",
                     "summary_info", "tl_intensity", "sport_data_summary",
                     "training_week_stages"):
            assert key in result
        assert result["sport_data_summary"]["totalActivityCount"] == 42

    @pytest.mark.asyncio
    async def test_parses_daily_record_fields(self):
        auth = make_auth()
        with _patch_http(get_resp=_analysis_side_effect):
            result = await fetch_training_analysis(auth, "20260515", "20260522")

        rec = result["daily_records"][0]
        assert rec["date"] == "20260515"
        assert rec["rhr"] == 60
        assert rec["avg_sleep_hrv"] == 66.0
        assert rec["vo2max"] == 52
        assert rec["training_load"] == 39

    @pytest.mark.asyncio
    async def test_merges_t7daylist_gaps(self):
        """t7dayList fills None/0 gaps in dayDetail records."""
        auth = make_auth()
        detail_item = {**DAY_ITEM, "avgSleepHrv": None, "rhr": 0}

        def side_effect(url, **kwargs):
            if "dayDetail" in url:
                return _resp({"result": "0000", "data": {"dayList": [detail_item]}})
            return _resp({
                "result": "0000",
                "data": {
                    "t7dayList": [{"happenDay": 20260515, "avgSleepHrv": 55.0, "rhr": 62}],
                    "weekList": [], "record": {}, "sportStatistic": [],
                    "summaryInfo": {}, "tlIntensity": {},
                    "sportDataSummary": {}, "trainingWeekStageList": [],
                },
            })

        with _patch_http(get_resp=side_effect):
            result = await fetch_training_analysis(auth, "20260515", "20260522")

        rec = result["daily_records"][0]
        assert rec["avg_sleep_hrv"] == 55.0  # from t7dayList
        assert rec["rhr"] == 62

    @pytest.mark.asyncio
    async def test_raises_on_api_error(self):
        auth = make_auth()
        with _patch_http(get_resp=_resp(API_ERROR)):
            with pytest.raises(ValueError, match="Coros analyse error"):
                await fetch_training_analysis(auth, "20260515", "20260522")


# ---------------------------------------------------------------------------
# fetch_training_library — SSR page + paginated API, no auth
# ---------------------------------------------------------------------------

SSR_HTML = '<html><body><script>window.__INITIAL_STATE__ = {"csrf":"csrf-abc","country":"cn"};</script></body></html>'

LIBRARY_API_RESP = {
    "result": "0000",
    "data": {
        "list": [
            {
                "_id": "abc123", "linked_id": "476133458610143331",
                "title": "VO2max Interval", "category": "workout",
                "sport_type": ["run"], "difficulty": ["advanced"],
                "workout_target": ["vo2max"],
                "author": "coros", "author_i18n": "COROS Coaches",
                "download_count": 1520,
                "content": "", "iconType": 1, "region": 1,
                "createdAt": "2024-01-01", "updatedAt": "2025-06-01",
            },
        ],
        "pagination": {"total": 1, "offset": 0, "limit": 50},
    },
}


def _library_side_effect(url, **kwargs):
    if "api" not in url:
        return MockResponse(text=SSR_HTML)
    return _resp(LIBRARY_API_RESP)


class TestFetchTrainingLibrary:
    @pytest.mark.asyncio
    async def test_parses_programs(self):
        with _patch_http(get_resp=_library_side_effect):
            programs = await fetch_training_library("cn", "zh-CN")

        assert len(programs) == 1
        p = programs[0]
        assert p.title == "VO2max Interval"
        assert p.linked_id == "476133458610143331"
        assert p.category == "workout"

    @pytest.mark.asyncio
    async def test_filters_by_category(self):
        with _patch_http(get_resp=_library_side_effect):
            programs = await fetch_training_library("cn", "zh-CN", category="plan")
        assert programs == []

    @pytest.mark.asyncio
    async def test_filters_by_sport_and_difficulty(self):
        with _patch_http(get_resp=_library_side_effect):
            assert await fetch_training_library("cn", "zh-CN", sport_type="cycling") == []
            assert await fetch_training_library("cn", "zh-CN", sport_type="run") != []
            assert await fetch_training_library("cn", "zh-CN", difficulty="beginner") == []
            assert await fetch_training_library("cn", "zh-CN", difficulty="advanced") != []

    @pytest.mark.asyncio
    async def test_raises_when_no_ssr_state(self):
        with _patch_http(get_resp=_resp(text="<html>nothing</html>")):
            with pytest.raises(ValueError, match="__INITIAL_STATE__"):
                await fetch_training_library("cn", "zh-CN")


# ---------------------------------------------------------------------------
# import_training_program — GET detail → POST copy, workout vs plan endpoints
# ---------------------------------------------------------------------------

DETAIL_RESP = {
    "result": "0000",
    "data": {"id": "workout-789", "name": "W30050", "programType": 1,
             "exercises": [{"name": "Warm-up", "duration": 600}]},
}

IMPORT_RESP = {
    "result": "0000",
    "data": {"id": "imported-001", "name": "VO2max Interval",
             "exerciseNum": 7, "estimatedTime": 3540},
}


def _import_client():
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(DETAIL_RESP))
    client.post = AsyncMock(return_value=_resp(IMPORT_RESP))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestImportTrainingProgram:
    @pytest.mark.asyncio
    async def test_get_detail_then_post_copy(self):
        auth = make_auth()
        with patch("httpx.AsyncClient", return_value=_import_client()):
            result = await import_training_program(
                auth, "linked-123", "workout", 1, name="VO2max Interval")

        assert result["imported_id"] == "imported-001"
        assert result["name"] == "VO2max Interval"

    @pytest.mark.asyncio
    async def test_injects_custom_name_into_post_body(self):
        auth = make_auth()
        client = _import_client()
        with patch("httpx.AsyncClient", return_value=client):
            await import_training_program(auth, "linked-123", "workout", 1,
                                          name="My VO2max")

        assert client.post.call_args[1]["json"]["name"] == "My VO2max"

    @pytest.mark.asyncio
    async def test_plan_uses_different_endpoints(self):
        auth = make_auth()
        client = _import_client()
        with patch("httpx.AsyncClient", return_value=client):
            await import_training_program(auth, "linked-plan", "plan", 1,
                                          name="Plan")

        assert "plan/detail" in client.get.call_args[0][0]
        assert "plan/copy" in client.post.call_args[0][0]

    @pytest.mark.asyncio
    async def test_raises_on_detail_error(self):
        auth = make_auth()
        with _patch_http(get_resp=_resp(API_ERROR)):
            with pytest.raises(ValueError, match="Coros workout detail error"):
                await import_training_program(auth, "bad", "workout", 1)
