"""
Coros Training Hub API client.

Auth mechanism: MD5-hashed password + accessToken header.
HRV data comes from /dashboard/query (last 7 days of nightly RMSSD).
Sleep phase data comes from the mobile API (/coros/data/statistic/daily on apieu.coros.com).
"""

import asyncio
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Optional

import httpx

from auth.storage import get_token, store_token
from models import ActivitySummary, DailyHealthRecord, DailyRecord, SleepPhases, SleepRecord, StressRecord, StoredAuth, TrainingProgram

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

MOBILE_LOGIN_ENDPOINT = "/coros/user/login"

# AES key hardcoded in libencrypt-lib.so (reverse-engineered from Coros APK)
_MOBILE_AES_IV = b"weloop3_2015_03#"

ENDPOINTS = {
    "login": "/account/login",
    "dashboard": "/dashboard/query",        # contains sleepHrvData (last 7 days)
    "analyse": "/analyse/query",            # summary + t7dayList (28 days, has VO2max/fitness)
    "analyse_detail": "/analyse/dayDetail/query",  # daily metrics with date range (up to 24 weeks)
    "sleep": "/coros/data/statistic/daily",  # mobile API (apieu.coros.com)
    "activity_list": "/activity/query",
    "activity_detail": "/activity/detail/query",
    "sport_types": "/activity/fit/getImportSportList",
    "workout_list": "/training/program/query",  # POST — list/fetch workout programs
    "workout_add": "/training/program/add",     # POST — create new structured workout
    "workout_delete": "/training/program/delete",  # POST — delete workout(s), body: ["id1", ...]
    "schedule_sum": "/training/schedule/querysum",  # GET — planned calendar aggregates
    "schedule": "/training/schedule/query",         # GET — planned calendar detail
    "schedule_update": "/training/schedule/update", # POST — add workout to calendar
    "exercises": "/training/exercise/query",        # GET — exercise catalogue by sport type
    "account_query": "/account/query",             # GET — user profile, HR zones, maxHr, rhr
}

# Login works on teamapi.coros.com but tokens are only valid on the
# region-specific API host.  Always use the regional URL for all calls.
BASE_URLS = {
    "eu": "https://teameuapi.coros.com",
    "us": "https://teamapi.coros.com",
    "asia": "https://teamcnapi.coros.com",
    "cn": "https://teamcnapi.coros.com",
}

# Mobile app API — used for sleep data (different host from Training Hub web API)
MOBILE_BASE_URLS = {
    "eu": "https://apieu.coros.com",
    "us": "https://api.coros.com",
    "asia": "https://apicn.coros.com",
    "cn": "https://apicn.coros.com",
}

TOKEN_TTL_MS = 24 * 60 * 60 * 1000  # 24 hours in milliseconds


def _check_response(body: dict, context: str) -> None:
    """Raise ValueError if the Coros API response indicates an error."""
    if body.get("result") != "0000":
        raise ValueError(f"Coros {context} error: {body.get('message', 'unknown error')}")


# ---------------------------------------------------------------------------
# Token storage  (keyring → encrypted file, managed by auth.storage)
# ---------------------------------------------------------------------------

def _save_auth(auth: StoredAuth) -> None:
    store_token(auth.model_dump_json())


def _load_auth() -> Optional[StoredAuth]:
    result = get_token()
    if not result.success or not result.token:
        return None
    try:
        data = json.loads(result.token)
        return StoredAuth(**data)
    except Exception:
        return None


def _is_token_valid(auth: StoredAuth) -> bool:
    now_ms = int(time.time() * 1000)
    return (now_ms - auth.timestamp) < TOKEN_TTL_MS


# ---------------------------------------------------------------------------
# Mobile API encryption  (AES-128-CBC, key reverse-engineered from APK)
# ---------------------------------------------------------------------------

def _mobile_encrypt(plaintext: str, app_key: str) -> str:
    """
    Encrypt a string for the Coros mobile login API.

    Scheme reverse-engineered from libencrypt-lib.so in the Coros Android APK:
      1. XOR plaintext bytes with appKey bytes cyclically
      2. PKCS7-pad the XOR'd result to a 16-byte boundary
      3. AES-128-CBC encrypt: key = appKey bytes, IV = 'weloop3_2015_03#'
      4. Base64-encode the ciphertext
    """
    from Crypto.Cipher import AES
    import base64

    key = app_key.encode("ascii")
    data = plaintext.encode("utf-8")
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    pad_len = 16 - (len(xored) % 16)
    padded = xored + bytes([pad_len] * pad_len)
    cipher = AES.new(key, AES.MODE_CBC, _MOBILE_AES_IV)
    return base64.b64encode(cipher.encrypt(padded)).decode("ascii")


async def _mobile_login(email: str, password: str, region: str = "eu") -> tuple[str, dict]:
    """
    Authenticate against the Coros mobile API with encrypted credentials.

    Returns (access_token, login_payload_for_replay).
    The login_payload can be replayed to refresh the token without re-entering credentials.
    """
    mobile_base = MOBILE_BASE_URLS.get(region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + MOBILE_LOGIN_ENDPOINT
    app_key = str(random.randint(1_000_000_000_000_000, 9_999_999_999_999_999))
    payload = {
        "account": _mobile_encrypt(email, app_key) + "\n",
        "accountType": 2,
        "appKey": app_key,
        "clientType": 1,
        "hasHrCalibrated": 0,
        "kbValidity": 0,
        "pwd": _mobile_encrypt(_md5(password), app_key) + "\n",
        "region": "310|Europe/Berlin|US",
        "skipValidation": False,
    }
    yfheader = json.dumps({
        "appVersion": 1125917087236096,
        "clientType": 1,
        "language": "en-US",
        "mobileName": "sdk_gphone64_arm64,google,Google",
        "releaseType": 1,
        "systemVersion": "13",
        "timezone": 4,
        "versionCode": "404080400",
    }, separators=(",", ":"))
    headers = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
        "yfheader": yfheader,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "mobile login")

    token = body.get("data", {}).get("accessToken")
    if not token:
        raise ValueError("No accessToken in Coros mobile login response")

    return token, payload


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS["eu"])


async def login(email: str, password: str, region: str = "eu", *, skip_mobile: bool = False) -> StoredAuth:
    """Authenticate against Coros API and persist the token."""
    pwd_hash = _md5(password)
    login_payload = {
        "account": email,
        "accountType": 2,
        "pwd": pwd_hash,
    }
    json_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=30) as client:
        # Training Hub token (teameuapi.coros.com)
        resp = await client.post(
            _base_url(region) + ENDPOINTS["login"],
            json=login_payload,
            headers=json_headers,
        )
        resp.raise_for_status()
        body = resp.json()

        _check_response(body, "login")

        data = body.get("data", {})

    # Mobile API token (apieu.coros.com) — needed for sleep data
    # Uses AES-encrypted credentials (key reverse-engineered from libencrypt-lib.so)
    mobile_token = None
    mobile_payload = None
    if not skip_mobile:
        try:
            mobile_token, mobile_payload = await _mobile_login(email, password, region)
        except Exception:
            pass  # mobile login is best-effort; sleep data will fail gracefully

    auth = StoredAuth(
        access_token=data["accessToken"],
        user_id=data["userId"],
        region=region,
        timestamp=int(time.time() * 1000),
        mobile_access_token=mobile_token,
        mobile_login_payload=mobile_payload,
    )
    _save_auth(auth)
    return auth


async def login_mobile(email: str, password: str, region: str = "eu") -> StoredAuth:
    """Authenticate against the Coros mobile API only and persist the token.

    If an existing StoredAuth exists, updates only the mobile fields.
    Otherwise creates a minimal StoredAuth with only mobile credentials.
    """
    mobile_token, mobile_payload = await _mobile_login(email, password, region)

    existing = _load_auth()
    if existing:
        existing = existing.model_copy(update={
            "mobile_access_token": mobile_token,
            "mobile_login_payload": mobile_payload,
        })
        _save_auth(existing)
        return existing

    auth = StoredAuth(
        access_token="",
        user_id="",
        region=region,
        timestamp=int(time.time() * 1000),
        mobile_access_token=mobile_token,
        mobile_login_payload=mobile_payload,
    )
    _save_auth(auth)
    return auth


def get_stored_auth() -> Optional[StoredAuth]:
    """Return stored auth if it exists and is not expired.
    
    When COROS_ACCESS_TOKEN env var is set, it takes precedence over
    stored keyring/encrypted-file auth (for MCP server use cases where
    keyring is not accessible in the subprocess).
    """
    # Prefer explicit env var token when provided
    access_token = os.environ.get("COROS_ACCESS_TOKEN")
    if access_token:
        region = os.environ.get("COROS_REGION", "eu")
        return StoredAuth(
            access_token=access_token,
            user_id="env",
            region=region,
            timestamp=int(time.time() * 1000),
            mobile_access_token=None,
            mobile_login_payload=None,
        )
    # Fall back to stored auth
    auth = _load_auth()
    if auth and _is_token_valid(auth):
        return auth
    return None


def get_env_credentials() -> Optional[tuple[str, str, str]]:
    """Return (email, password, region) from env vars, or None if not fully set."""
    email = os.environ.get("COROS_EMAIL")
    password = os.environ.get("COROS_PASSWORD")
    region = os.environ.get("COROS_REGION", "eu")
    if email and password:
        return email, password, region
    return None


async def try_auto_login() -> Optional[StoredAuth]:
    """Attempt login using COROS_EMAIL/PASSWORD env vars. Returns None on failure.

    Also obtains a mobile API token so that sleep data (deep/light/REM/awake)
    is available immediately without a separate auth-mobile step.
    """
    creds = get_env_credentials()
    if creds is None:
        return None
    email, password, region = creds
    try:
        return await login(email, password, region)  # skip_mobile=True by default
    except Exception:
        return None


# ---------------------------------------------------------------------------
# API headers
# ---------------------------------------------------------------------------

def _auth_headers(auth: StoredAuth) -> dict:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "accessToken": auth.access_token,
        "yfheader": json.dumps({"userId": auth.user_id}),
    }


# ---------------------------------------------------------------------------
# Dashboard snapshot  (/dashboard/query)
# ---------------------------------------------------------------------------

async def fetch_dashboard(auth: StoredAuth) -> dict:
    """
    Fetch the full Coros dashboard snapshot for quick athlete-state assessment.

    Calls /dashboard/query which returns current summary data (typically the
    last 7 days plus today) without requiring date parameters.  The response
    includes HRV data, sleep quality, training readiness, recent activity
    summaries, and fitness trends — everything the Coros app dashboard shows.

    Returns
    -------
    dict — the full data payload from the dashboard endpoint.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["dashboard"],
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "dashboard")
    return body.get("data", {})


# ---------------------------------------------------------------------------
# Daily analysis data  (/analyse/dayDetail/query — up to 24 weeks)
# ---------------------------------------------------------------------------

def _parse_daily_record(item: dict) -> DailyRecord:
    """Parse a single day record from either endpoint — all 35 fields."""
    return DailyRecord(
        # Core
        date=str(item.get("happenDay", "")),
        timestamp=item.get("timestamp"),
        # HRV & Sleep
        avg_sleep_hrv=item.get("avgSleepHrv"),
        baseline=item.get("sleepHrvBase"),
        interval_list=item.get("sleepHrvIntervalList"),
        # Heart rate
        rhr=item.get("rhr"),
        test_rhr=item.get("testRhr"),
        lthr=item.get("lthr"),
        # Training load
        training_load=item.get("trainingLoad"),
        training_load_target=item.get("trainingLoadTarget"),
        training_load_ratio=item.get("trainingLoadRatio"),
        training_load_ratio_state=item.get("trainingLoadRatioState"),
        training_load_ratio_zone_list=item.get("trainingLoadRatioZoneList"),
        t7d=item.get("t7d"),
        t28d=item.get("t28d"),
        ct7d_max_fixed=item.get("ct7dMaxFixed"),
        ct7d_min=item.get("ct7dMin"),
        recomend_tl_max=item.get("recomendTlMax"),
        recomend_tl_min=item.get("recomendTlMin"),
        # Fatigue
        tired_rate=item.get("tiredRateNew"),
        tired_rate_old=item.get("tiredRate"),
        tired_rate_state_new=item.get("tiredRateStateNew"),
        tired_rate_new_zone_list=item.get("tiredRateNewZoneList"),
        tib=item.get("tib"),
        # Performance
        ati=item.get("ati"),
        cti=item.get("cti"),
        performance=item.get("performance"),
        # Volume
        distance=item.get("distance"),
        distance_target=item.get("distanceTarget"),
        duration=item.get("duration"),
        duration_target=item.get("durationTarget"),
        # VO2max & stamina
        vo2max=item.get("vo2max"),
        stamina_level=item.get("staminaLevel"),
        stamina_level_7d=item.get("staminaLevel7d"),
        # Pace
        ltsp=item.get("ltsp"),
    )


async def fetch_training_analysis(
    auth: StoredAuth, start_day: str, end_day: str
) -> dict:
    """
    Fetch the full Coros training analysis ("数据分析") for a date range.

    Merges data from two endpoints in parallel:
    - /analyse/dayDetail/query — configurable range (up to 24 weeks), 35 fields
      per day including HRV
    - /analyse/query — fixed 84-day window, 9 sections including records,
      summaries, distributions

    Returns
    -------
    dict with keys:

      daily_records (list[dict])
          Parsed DailyRecord objects (35 fields each) for the requested range,
          built from dayDetail and augmented with t7dayList where gaps exist.

      week_list (list[dict])
          12 weekly summaries: firstDayOfWeek, trainingLoad,
          recomendTlMin, recomendTlMax.

      records (dict)
          Personal records: distanceRecord, durationRecord, tlRecord.

      sport_statistic (list[dict])
          Per-sport aggregated stats: sportType, count, distance, duration,
          trainingLoad, avgHeartRate, avgPace.

      summary_info (dict)
          10 distribution charts: disAreaList, timeAreaList, tlAreaList,
          distanceCountAreaList, distanceTimeAreaList, distanceTlAreaList,
          hrDisAreaList, hrTimeAreaList, hrTlAreaList, recomendTlInDays.

      tl_intensity (dict)
          Weekly training load intensity breakdown: periodLowPct,
          periodMediumPct, periodHighPct over 6 weeks.

      sport_data_summary (dict)
          Total activity count and model validity status.

      training_week_stages (list)
          Training phase stages (may be empty).
    """
    headers = _auth_headers(auth)
    base = _base_url(auth.region)

    async with httpx.AsyncClient(timeout=30) as client:
        detail_resp, analyse_resp = await asyncio.gather(
            client.get(
                base + ENDPOINTS["analyse_detail"],
                params={"startDay": start_day, "endDay": end_day},
                headers=headers,
            ),
            client.get(
                base + ENDPOINTS["analyse"],
                headers=headers,
            ),
        )
    detail_resp.raise_for_status()
    detail_body = detail_resp.json()
    analyse_resp.raise_for_status()
    analyse_body = analyse_resp.json()

    _check_response(detail_body, "analyse")

    # Build daily records from dayDetail (configurable range, 35 fields)
    records_by_date: dict[str, DailyRecord] = {}
    for item in detail_body.get("data", {}).get("dayList", []):
        rec = _parse_daily_record(item)
        records_by_date[rec.date] = rec

    # Merge from /analyse/query t7dayList (28-day rolling, fills HRV gaps)
    analyse_data = analyse_body.get("data", {})
    if analyse_body.get("result") == "0000":
        for item in analyse_data.get("t7dayList", []):
            date = str(item.get("happenDay", ""))
            if date in records_by_date:
                rec = records_by_date[date]
                t7 = _parse_daily_record(item)
                for field_name in DailyRecord.model_fields:
                    if field_name == "date":
                        continue
                    existing = getattr(rec, field_name)
                    if existing is None or existing == 0:
                        t7_val = getattr(t7, field_name)
                        if t7_val is not None:
                            setattr(rec, field_name, t7_val)

    daily = sorted(records_by_date.values(), key=lambda r: r.date)

    return {
        "daily_records": [r.model_dump() for r in daily],
        "week_list": analyse_data.get("weekList", []),
        "records": analyse_data.get("record", {}),
        "sport_statistic": analyse_data.get("sportStatistic", []),
        "summary_info": analyse_data.get("summaryInfo", {}),
        "tl_intensity": analyse_data.get("tlIntensity", {}),
        "sport_data_summary": analyse_data.get("sportDataSummary", {}),
        "training_week_stages": analyse_data.get("trainingWeekStageList", []),
    }


# ---------------------------------------------------------------------------
# Sport types  (/activity/fit/getImportSportList)
# ---------------------------------------------------------------------------

async def fetch_sport_types(auth: StoredAuth) -> list[dict]:
    """
    Fetch the full list of sport types supported by Coros.

    Returns the canonical sport type catalogue from the server, including
    sportType IDs and display names.  Use this to discover available sport
    IDs when creating workouts or filtering activities.

    Returns
    -------
    list[dict] with keys such as sportType, sportName, parentSportType, etc.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["sport_types"],
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "sport types")
    return body.get("data", []) or []


# ---------------------------------------------------------------------------
# Activity data
# ---------------------------------------------------------------------------

SPORT_NAMES: dict[int, str] = {
    100: "Running", 102: "Trail Running", 103: "Track Running", 104: "Hiking",
    200: "Road Bike", 201: "Indoor Cycling", 203: "Gravel Bike", 204: "MTB",
    400: "Cardio", 402: "Strength", 403: "Yoga",
    900: "Walking", 9807: "Bike Commute",
}


def _parse_activity(item: dict) -> ActivitySummary:
    sport_type = item.get("sportType")
    return ActivitySummary(
        activity_id=str(item.get("labelId", "")),
        name=item.get("name") or item.get("remark"),
        sport_type=sport_type,
        sport_name=SPORT_NAMES.get(sport_type, f"Sport {sport_type}") if sport_type else None,
        start_time=str(item["startTime"]) if item.get("startTime") else None,
        end_time=str(item["endTime"]) if item.get("endTime") else None,
        duration_seconds=item.get("totalTime"),
        distance_meters=item.get("distance") or item.get("totalDistance"),
        avg_hr=item.get("avgHr"),
        max_hr=item.get("maxHr"),
        calories=round((item.get("calorie") or item.get("totalCalorie") or 0) / 1000) or None,
        training_load=item.get("trainingLoad"),
        avg_power=item.get("avgPower"),
        normalized_power=item.get("np"),
        elevation_gain=item.get("ascent") or item.get("totalAscent") or item.get("elevationGain"),
    )


async def fetch_activities(
    auth: StoredAuth,
    start_day: str,
    end_day: str,
    page: int = 1,
    size: int = 30,
    mode_list: Optional[list[int]] = None,
) -> tuple[list[ActivitySummary], int]:
    """
    Fetch activity list for a date range.
    Returns (activities, total_count).
    """
    params: dict = {
        "startDay": start_day,
        "endDay": end_day,
        "pageNumber": page,
        "size": size,
    }
    if mode_list:
        params["modeList"] = ",".join(str(m) for m in mode_list)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["activity_list"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "activity list")

    data = body.get("data", {})
    items = data.get("dataList", data.get("list", []))
    total = data.get("totalCount") or data.get("count") or len(items)
    return [_parse_activity(i) for i in items], total


async def fetch_activity_detail(auth: StoredAuth, activity_id: str, sport_type: int = 0) -> dict:
    """
    Fetch full activity detail including laps, HR zones, and metrics.
    Returns raw API data dict.
    Requires sport_type (e.g. 200=Road Bike, 201=Indoor Cycling, 100=Running).
    """
    headers = {k: v for k, v in _auth_headers(auth).items() if k != "Content-Type"}
    url = _base_url(auth.region) + ENDPOINTS["activity_detail"]
    form_data = {"labelId": activity_id, "userId": auth.user_id, "sportType": str(sport_type)}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, data=form_data, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "activity detail")

    data = body.get("data", {})
    # Strip large time-series arrays that bloat the response
    for key in ("graphList", "frequencyList", "gpsLightDuration"):
        data.pop(key, None)
    return data


# ---------------------------------------------------------------------------
# Workout programs  (/training/program/query + /training/program/add)
# ---------------------------------------------------------------------------

# sportType=2 = Indoor Cycling (Rollen); intensityType=6 = power in watts
# targetType=2 = time-based (seconds); exerciseType=2 = cycling block

WORKOUT_SPORT_NAMES: dict[int, str] = {
    2: "Indoor Cycling",
    4: "Strength",
    100: "Running",
    200: "Road Bike",
    201: "Indoor Cycling (alt)",
}


def _parse_workout(item: dict) -> dict:
    exercises = []
    for ex in item.get("exercises", []):
        exercises.append({
            "name": ex.get("name"),
            "duration_seconds": ex.get("targetValue"),
            "power_low_w": ex.get("intensityValue"),
            "power_high_w": ex.get("intensityValueExtend"),
            "intensity_type": ex.get("intensityType"),
            "hr_type": ex.get("hrType"),
            "intensity_percent": ex.get("intensityPercent"),
            "intensity_percent_extend": ex.get("intensityPercentExtend"),
            "overview": ex.get("overview"),
            "rest_seconds": ex.get("restValue"),
            "sort_no": ex.get("sortNo"),
            "sets": ex.get("sets", 1),
        })
    sport = item.get("sportType")
    return {
        "id": str(item.get("id", "")),
        "name": item.get("name"),
        "sport_type": sport,
        "sport_name": WORKOUT_SPORT_NAMES.get(sport, f"Sport {sport}"),
        "estimated_time_seconds": item.get("estimatedTime"),
        "estimated_distance": item.get("estimatedDistance"),
        "training_load": item.get("trainingLoad"),
        "create_timestamp": item.get("createTimestamp"),
        "exercise_count": item.get("exerciseNum", len(exercises)),
        "exercises": exercises,
    }


async def fetch_workouts(auth: StoredAuth) -> list[dict]:
    """List all user workout programs."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_list"],
            json={},
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "workout list")

    return [_parse_workout(w) for w in body.get("data", [])]


def _build_power_exercise(
    *,
    ex_id: int,
    name: str,
    sport_type: int,
    power_low: int,
    power_high: int,
    target_value: int,
    sort_no: int,
    group_id: str,
) -> dict:
    return {
        "id": ex_id, "name": name, "exerciseType": 2,
        "sportType": sport_type, "intensityType": 6,
        "intensityValue": power_low, "intensityValueExtend": power_high,
        "targetType": 2, "targetValue": target_value,
        "sets": 1, "sortNo": sort_no,
        "restType": 3, "restValue": 0,
        "groupId": group_id, "isGroup": False, "originId": "0",
    }


async def create_workout(
    auth: StoredAuth,
    name: str,
    steps: list[dict],
    sport_type: int = 2,
) -> str:
    """
    Create a new structured workout program.

    steps: list of dicts — either plain steps or repeat groups.

    Plain step:
      - name: str — step label (e.g. "10:00 Einfahren")
      - duration_minutes: float — step duration in minutes
      - power_low_w: int — lower power target in watts
      - power_high_w: int — upper power target in watts (0 = open-ended)

    Repeat group:
      - repeat: int — number of repetitions
      - steps: list[dict] — sub-steps (same format as plain steps)

    Returns the new workout ID.
    """
    exercises = []
    top_index = 0
    total_seconds = 0
    ex_id = 0

    for step in steps:
        if "repeat" in step:
            top_index += 1
            ex_id += 1
            group_sort = 16777216 * top_index
            group_id = ex_id

            sub_steps = step["steps"]
            iteration_seconds = sum(
                int(s["duration_minutes"] * 60) for s in sub_steps
            )
            total_seconds += iteration_seconds * step["repeat"]

            exercises.append({
                "id": group_id,
                "name": "Group",
                "exerciseType": 0,
                "sportType": sport_type,
                "intensityType": 0,
                "intensityValue": 0,
                "targetType": 2,
                "targetValue": iteration_seconds,
                "sets": step["repeat"],
                "sortNo": group_sort,
                "restType": 3,
                "restValue": 0,
                "groupId": "0",
                "isGroup": True,
                "originId": "0",
            })

            for j, sub in enumerate(sub_steps):
                ex_id += 1
                ex = _build_power_exercise(
                    ex_id=ex_id, name=sub["name"], sport_type=sport_type,
                    power_low=sub["power_low_w"],
                    power_high=sub.get("power_high_w", 0),
                    target_value=int(sub["duration_minutes"] * 60),
                    sort_no=group_sort + 65536 * (j + 1),
                    group_id=str(group_id),
                )
                exercises.append(ex)
        else:
            top_index += 1
            ex_id += 1
            duration_s = int(step["duration_minutes"] * 60)
            total_seconds += duration_s
            ex = _build_power_exercise(
                ex_id=ex_id, name=step["name"], sport_type=sport_type,
                power_low=step["power_low_w"],
                power_high=step.get("power_high_w", 0),
                target_value=duration_s,
                sort_no=16777216 * top_index,
                group_id="0",
            )
            exercises.append(ex)

    payload = {
        "name": name,
        "sportType": sport_type,
        "estimatedTime": total_seconds,
        "access": 1,
        "exercises": exercises,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_add"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "workout create")

    return str(body.get("data", ""))


# ---------------------------------------------------------------------------
# Running workout helpers
# ---------------------------------------------------------------------------

def _pace_sec_per_km_to_mmss0(pace: int) -> int:
    """4:43/km = 283 sec/km → 4*10000 + 43*100 = 44300"""
    minutes = pace // 60
    seconds = pace % 60
    return minutes * 10000 + seconds * 100


def _is_zone_mode(steps: list[dict]) -> bool:
    """hr_low in 1-6 → zone number; >6 → absolute bpm."""
    for step in steps:
        if "repeat" in step:
            for sub in step.get("steps", []):
                if 1 <= sub.get("hr_low", 0) <= 6:
                    return True
        elif 1 <= step.get("hr_low", 0) <= 6:
            return True
    return False


def _zone_to_bpm(zone: int, zones: list[dict]) -> tuple[int, int]:
    """Look up bpm range from pre-computed zone boundary table.

    Boundary table has 6 entries demarcating 6 zones:
      Z1: 0 .. boundary[0]
      Z2: boundary[0] .. boundary[1]
      ZN: boundary[N-2] .. boundary[N-1]
    """
    if zone == 1:
        return 0, zones[0]["hr"]
    return zones[zone - 2]["hr"], zones[zone - 1]["hr"]


def _zone_to_percent(zone: int, zones: list[dict]) -> tuple[int, int]:
    """Look up percentage range from zone table ratios.

    Returns (ratio_low, ratio_high) in COROS integer format: 59000 = 59%.
    Z1 returns (0, int(boundary[0].ratio * 1000)).
    """
    if zone == 1:
        return 0, int(zones[0]["ratio"] * 1000)
    return int(zones[zone - 2]["ratio"] * 1000), int(zones[zone - 1]["ratio"] * 1000)


# intensityMultiplier: 0 for HR/power/cadence types, 1000 for pace types
_INTENSITY_MULTIPLIER = {2: 0, 3: 1000, 6: 0, 7: 0, 8: 1000}


def _multiplier_for(intensity_type: int) -> int:
    return _INTENSITY_MULTIPLIER.get(intensity_type, 0)


def _resolve_intensity(
    step: dict,
    intensity_type: int,
    mult: int,
    use_zone: bool,
    zone_table: list[dict] | None,
) -> tuple[int, int, int | None]:
    """Resolve intensity values from a step dict.

    Returns (intensity_value, intensity_extend, zone_low).
    zone_low is the zone number for zone mode (used later for intensityPercent),
    None for BPM/pace mode.
    """
    zone_low = None
    if intensity_type in (3, 8) and "pace_low" in step:
        ival = step["pace_low"] * mult
        iext = step.get("pace_high", step["pace_low"]) * mult
    elif use_zone:
        zone_low = step.get("hr_low")
        ival, iext = _zone_to_bpm(zone_low, zone_table)
    else:
        ival = step.get("hr_low", 0)
        iext = step.get("hr_high", step.get("hr_low", 0))
    return ival, iext, zone_low


def _build_run_exercise(
    *,
    ex_id: int,
    name: str,
    sport_type: int,
    intensity_type: int,
    intensity_value: int,
    intensity_extend: int,
    target_value: int,
    sort_no: int,
    group_id: str,
    mult: int,
    hr_type: int,
    use_zone: bool,
    zone_low: int | None,
    zone_table: list[dict] | None,
) -> dict:
    ex = {
        "id": ex_id, "name": name, "exerciseType": 2,
        "sportType": sport_type, "intensityType": intensity_type,
        "intensityValue": intensity_value, "intensityValueExtend": intensity_extend,
        "intensityMultiplier": mult,
        "targetType": 2, "targetValue": target_value,
        "targetDisplayUnit": 0, "subType": 0, "sourceId": "0",
        "sets": 1, "sortNo": sort_no,
        "restType": 3, "restValue": 0, "overview": "sid_run_training",
        "groupId": group_id, "isGroup": False, "originId": "0",
    }
    if hr_type and intensity_type not in (3, 8):
        ex["hrType"] = hr_type
    if use_zone and intensity_type == 2 and zone_low is not None and zone_table is not None:
        pct_low, pct_high = _zone_to_percent(zone_low, zone_table)
        ex["intensityPercent"] = pct_low
        ex["intensityPercentExtend"] = pct_high
        ex["isIntensityPercent"] = True
    return ex


async def create_run_workout(
    auth: StoredAuth,
    name: str,
    steps: list[dict],
    sport_type: int = 1,
    hr_type: int = 3,
    intensity_type: int = 2,
    value_type: int | None = None,
) -> str:
    """Create a running workout with HR targets.

    Zone mode (hr_low 1-6): auto-looks up bpm from COROS zone tables.
    BPM mode (hr_low > 6): absolute bpm values passed directly.

    Fetches user profile from /account/query so zone boundaries match the
    COROS App exactly — no manual percentage calculation needed.

    Parameters
    ----------
    name : str
    steps : list[dict] — name, duration_minutes, hr_low[, hr_high, pace_low, pace_high]
    sport_type : int — 1=Running
    hr_type : int — 1=MaxHR, 2=%HRR, 3=%LTHR
    """
    use_zone = _is_zone_mode(steps)

    if use_zone:
        profile = await fetch_user_profile(auth)
        zone_table = profile["zones"].get(hr_type)
        if not zone_table or len(zone_table) < 6:
            raise ValueError(f"No zone data for hr_type={hr_type}")
    else:
        zone_table = None

    exercises = []
    top_index = 0
    total_seconds = 0
    ex_id = 0

    for step in steps:
        if "repeat" in step:
            top_index += 1
            ex_id += 1
            group_sort = 16777216 * top_index
            group_id = ex_id

            sub_steps = step["steps"]
            iteration_seconds = sum(
                int(s["duration_minutes"] * 60) for s in sub_steps
            )
            total_seconds += iteration_seconds * step["repeat"]

            exercises.append({
                "id": group_id, "name": "Group", "exerciseType": 0,
                "sportType": sport_type, "intensityType": 0, "intensityValue": 0,
                "targetType": 2, "targetValue": iteration_seconds,
                "sets": step["repeat"], "sortNo": group_sort,
                "restType": 3, "restValue": 0, "groupId": "0",
                "isGroup": True, "originId": "0",
            })

            for j, sub in enumerate(sub_steps):
                ex_id += 1
                sub_duration = int(sub["duration_minutes"] * 60)
                mult = _multiplier_for(intensity_type)
                ival, iext, zone_low = _resolve_intensity(
                    sub, intensity_type, mult, use_zone, zone_table)
                ex = _build_run_exercise(
                    ex_id=ex_id, name=sub["name"], sport_type=sport_type,
                    intensity_type=intensity_type,
                    intensity_value=ival, intensity_extend=iext,
                    target_value=sub_duration,
                    sort_no=group_sort + 65536 * (j + 1),
                    group_id=str(group_id), mult=mult,
                    hr_type=hr_type, use_zone=use_zone,
                    zone_low=zone_low, zone_table=zone_table,
                )
                exercises.append(ex)
        else:
            top_index += 1
            ex_id += 1
            duration_s = int(step["duration_minutes"] * 60)
            total_seconds += duration_s
            mult = _multiplier_for(intensity_type)
            ival, iext, zone_low = _resolve_intensity(
                step, intensity_type, mult, use_zone, zone_table)
            ex = _build_run_exercise(
                ex_id=ex_id, name=step["name"], sport_type=sport_type,
                intensity_type=intensity_type,
                intensity_value=ival, intensity_extend=iext,
                target_value=duration_s,
                sort_no=16777216 * top_index,
                group_id="0", mult=mult,
                hr_type=hr_type, use_zone=use_zone,
                zone_low=zone_low, zone_table=zone_table,
            )
            exercises.append(ex)

    if value_type is None:
        # Default: percentage display for HR types, absolute for pace/power/cadence
        value_type = 2 if intensity_type == 2 else 1
    payload = {
        "name": name,
        "sportType": sport_type,
        "estimatedTime": total_seconds,
        "access": 1,
        "type": 0,
        "subType": 65535,
        "exercises": exercises,
        "referExercise": {
            "hrType": hr_type,
            "intensityType": intensity_type,
            "valueType": value_type,
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_add"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "run workout create")

    return str(body.get("data", ""))


async def delete_workout(auth: StoredAuth, workout_id: str) -> None:
    """Delete a workout program by ID."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_delete"],
            json=[workout_id],
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "workout delete")


# ---------------------------------------------------------------------------
# Planned activities (training schedule calendar)
# ---------------------------------------------------------------------------

async def fetch_schedule(
    auth: StoredAuth, start_day: str, end_day: str
) -> list[dict]:
    """
    Fetch planned activities from the Coros training calendar.

    Uses GET /training/schedule/query with startDate/endDate params.
    start_day / end_day: YYYYMMDD strings.
    Returns the raw list of scheduled items.
    """
    params = {
        "startDate": start_day,
        "endDate": end_day,
        "supportRestExercise": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["schedule"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule")

    return _strip_schedule(body.get("data") or {})


# ---------------------------------------------------------------------------
# Training schedule summary  (/training/schedule/querysum — volume aggregates)
# ---------------------------------------------------------------------------

async def fetch_schedule_summary(
    auth: StoredAuth, start_day: str, end_day: str
) -> dict:
    """
    Fetch aggregated training calendar summary for a date range.

    Uses GET /training/schedule/querysum which returns high-level volume
    aggregates (total duration, training load, session count, weekly
    breakdowns) without the full workout detail that /schedule/query returns.

    start_day / end_day: YYYYMMDD strings.
    """
    params = {"startDate": start_day, "endDate": end_day}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["schedule_sum"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule summary")
    return body.get("data", {})


_EXERCISE_DROP = frozenset({
    "videoInfos", "videoUrl", "videoUrlArrStr", "coverUrlArrStr",
    "thumbnailUrl", "sourceUrl", "animationId",
    "access", "deleted", "defaultOrder", "status", "createTimestamp",
    "userId", "muscle", "muscleRelevance", "part", "equipment",
    "sortNo", "originId", "isDefaultAdd", "intensityCustom",
    "intensityDisplayUnit", "isIntensityPercent",
})

_PROGRAM_DROP = frozenset({
    "exerciseBarChart", "headPic", "profile", "sex", "star", "nickname",
    "essence", "originEssence", "access", "authorId", "deleted", "pbVersion",
    "version", "status", "createTimestamp", "thirdPartyId",
    "isTargetTypeConsistent", "pitch", "simple", "unit",
    "distanceDisplayUnit", "elevGain", "estimatedDistance", "estimatedTime",
    "estimatedType", "strengthType", "targetType", "targetValue",
    "planId", "planIdIndex", "userId",
})

_ENTITY_DROP = frozenset({
    "exerciseBarChart", "completeRate", "score", "standardRate",
    "dayNo", "operateUserId", "thirdParty", "thirdPartyId",
    "sortNo", "sortNoInSchedule", "userId", "planId", "planIdIndex",
})

_TOP_DROP = frozenset({
    "sportDatasInPlan", "sportDatasNotInPlan", "likeTpIds", "starTimestamp",
    "score", "sourceUrl", "inSchedule", "pauseInApp", "access", "authorId",
    "category", "pbVersion", "version", "thirdPartyId", "maxIdInPlan",
    "maxPlanProgramId", "weekStages", "subPlans", "userInfos",
    "type", "unit", "totalDay", "status", "startDay", "createTime",
    "updateTimestamp", "userId",
})


def _drop_keys(d: dict, keys: frozenset) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def _readable_overview(overview: str) -> str:
    """Convert 'sid_strength_squats' → 'Squats', 'sid_run_warm_up_dist' → 'Run warm up dist'."""
    for prefix in ("sid_strength_", "sid_run_", "sid_"):
        if overview.startswith(prefix):
            overview = overview[len(prefix):]
            break
    return overview.replace("_", " ").capitalize()


def _strip_exercise(ex: dict) -> dict:
    out = _drop_keys(ex, _EXERCISE_DROP)
    if "overview" in out:
        out["overview"] = _readable_overview(out["overview"])
    return out


def _strip_program(prog: dict) -> dict:
    out = _drop_keys(prog, _PROGRAM_DROP)
    if "exercises" in out:
        out["exercises"] = [_strip_exercise(e) for e in out["exercises"]]
    return out


def _strip_schedule(data: dict) -> dict:
    out = _drop_keys(data, _TOP_DROP)
    if "entities" in out:
        out["entities"] = [_drop_keys(e, _ENTITY_DROP) for e in out["entities"]]
    if "programs" in out:
        out["programs"] = [_strip_program(p) for p in out["programs"]]
    return out


async def create_strength_workout(
    auth: StoredAuth,
    name: str,
    exercises: list[dict],
    sets: int = 1,
) -> str:
    """
    Create a new structured strength workout program.

    exercises: list of dicts with keys:
      - origin_id: str  — exercise catalogue ID (from list_exercises)
      - name: str       — T-code name (e.g. "T1061")
      - overview: str   — sid_ key (e.g. "sid_strength_squats")
      - target_type: int — 2=time (seconds), 3=reps
      - target_value: int — seconds or reps
      - rest_seconds: int — rest after this exercise

    sets: number of circuit repetitions.

    Returns the new workout ID.
    """
    built = []
    total_duration = 0
    for i, ex in enumerate(exercises):
        target_value = ex["target_value"]
        rest = ex.get("rest_seconds", 60)
        total_duration += (target_value if ex["target_type"] == 2 else 0) + rest
        built.append({
            "access": 0,
            "createTimestamp": 0,
            "defaultOrder": i,
            "exerciseType": 2,
            "id": i + 1,
            "intensityCustom": 0,
            "intensityDisplayUnit": "6",
            "intensityMultiplier": 0,
            "intensityPercent": 0,
            "intensityPercentExtend": 0,
            "intensityType": 1,
            "intensityValue": 0,
            "intensityValueExtend": 0,
            "isDefaultAdd": 0,
            "isGroup": False,
            "isIntensityPercent": False,
            "hrType": 0,
            "name": ex.get("name", ""),
            "originId": ex["origin_id"],
            "overview": ex.get("overview", "sid_strength_training"),
            "part": [0],
            "groupId": "",
            "restType": 1,
            "restValue": rest,
            "sets": 1,
            "sortNo": i,
            "sourceUrl": "",
            "sportType": 4,
            "status": 1,
            "targetDisplayUnit": 0,
            "targetType": ex["target_type"],
            "targetValue": target_value,
            "userId": 0,
            "videoInfos": [],
            "videoUrl": "",
        })

    total_duration *= sets
    payload = {
        "access": 1,
        "authorId": "0",
        "createTimestamp": 0,
        "distance": "0",
        "duration": total_duration,
        "essence": 0,
        "estimatedType": 0,
        "estimatedValue": 0,
        "exerciseNum": len(exercises),
        "exercises": built,
        "headPic": "",
        "id": "0",
        "idInPlan": "0",
        "name": name,
        "nickname": "",
        "originEssence": 0,
        "overview": "",
        "pbVersion": 2,
        "pitch": 0,
        "planIdIndex": 0,
        "poolLength": 2500,
        "poolLengthId": 1,
        "poolLengthUnit": 2,
        "profile": "",
        "referExercise": {"intensityType": 1, "hrType": 0, "valueType": 1},
        "sex": 0,
        "sets": sets,
        "shareUrl": "",
        "simple": False,
        "sourceId": "425868113867882496",
        "sourceUrl": "",
        "sportType": 4,
        "star": 0,
        "subType": 65535,
        "targetType": 0,
        "targetValue": 0,
        "thirdPartyId": 0,
        "totalSets": sets,
        "trainingLoad": 0,
        "type": 0,
        "unit": 0,
        "userId": "0",
        "version": 0,
        "videoCoverUrl": "",
        "videoUrl": "",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_add"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "strength workout create")

    return str(body.get("data", ""))


async def _fetch_raw_workout(auth: StoredAuth, workout_id: str) -> Optional[dict]:
    """Return the raw workout object for a given ID from the workout list."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_list"],
            json={},
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()
    for w in body.get("data", []):
        if str(w.get("id", "")) == str(workout_id):
            return w
    return None


async def schedule_workout(
    auth: StoredAuth,
    workout_id: str,
    happen_day: str,
    sort_no: int = 1,
) -> None:
    """
    Add an existing workout to the Coros training calendar.

    happen_day: YYYYMMDD string.
    sort_no: order within the day (1 = first workout).
    """
    # Get raw workout object
    raw = await _fetch_raw_workout(auth, workout_id)
    if raw is None:
        raise ValueError(f"Workout {workout_id} not found in library.")

    # Build a clean program that matches what the Coros app produces
    # when the user manually creates a workout in the calendar.
    # The app identifies zone labels through `overview: "sid_run_training"`
    # and supporting fields — not through sourceId lookup.
    _EX_FIELD_MAP: dict[str, dict] = {
        # Maps raw-library field → fallback value when missing
        "exerciseType": {}, "groupId": {"default": "0"},
        "hrType": {}, "intensityMultiplier": {"default": 0},
        "intensityPercent": {}, "intensityPercentExtend": {},
        "intensityType": {}, "intensityValue": {},
        "intensityValueExtend": {}, "isGroup": {"default": False},
        "isIntensityPercent": {"default": True},
        "name": {}, "overview": {"default": "sid_run_training"},
        "restType": {"default": 3}, "restValue": {"default": 0},
        "sets": {"default": 1}, "sourceId": {"default": "0"},
        "sportType": {"default": 1}, "subType": {"default": 0},
        "targetDisplayUnit": {"default": 0}, "targetType": {"default": 2},
        "targetValue": {},
        # Fields the app sets on manual calendar workouts:
        "intensityCustom": {"default": 1},
        "intensityDisplayUnit": {"default": 0},
        "equipment": {"default": [1]},
        "part": {"default": [0]},
        "access": {"default": 0},
        "sourceUrl": {"default": ""},
        "videoUrl": {"default": ""},
    }
    _PR_FIELD_MAP: dict[str, dict] = {
        "type": {"default": 0}, "subType": {"default": 65535},
        "name": {}, "sportType": {}, "estimatedTime": {},
        "estimatedValue": {}, "distance": {"default": 0},
        "duration": {"default": 0}, "exerciseNum": {"default": 1},
        "hybridTotalSets": {}, "totalSets": {},
        "trainingLoad": {}, "exercises": {},
        "referExercise": {},
        "overview": {"default": ""},
        "sourceUrl": {"default": ""},
    }

    clean_exs: list[dict] = []
    for ex in raw.get("exercises", []):
        clean_ex: dict = {}
        for field, meta in _EX_FIELD_MAP.items():
            if field in ex:
                clean_ex[field] = ex[field]
            elif "default" in meta:
                clean_ex[field] = meta["default"]
        clean_exs.append(clean_ex)

    program: dict = {}
    for field, meta in _PR_FIELD_MAP.items():
        if field in raw:
            program[field] = raw[field]
        elif "default" in meta:
            program[field] = meta["default"]
    program["exercises"] = clean_exs

    # Fetch schedule to get maxIdInPlan (raw, not stripped)
    params = {
        "startDate": happen_day,
        "endDate": happen_day,
        "supportRestExercise": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["schedule"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        schedule_body = resp.json()

    raw_data = schedule_body.get("data") or {}
    try:
        id_in_plan = int(raw_data.get("maxIdInPlan", 0)) + 1
    except (TypeError, ValueError):
        id_in_plan = 1

    program["idInPlan"] = id_in_plan

    payload = {
        "entities": [{
            "happenDay": happen_day,
            "idInPlan": id_in_plan,
            "sortNoInSchedule": sort_no,
        }],
        "programs": [program],
        "versionObjects": [{"id": id_in_plan, "status": 1}],
        "pbVersion": 2,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["schedule_update"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule update")


async def remove_scheduled_workout(
    auth: StoredAuth,
    plan_id: str,
    id_in_plan: str,
    plan_program_id: Optional[str] = None,
) -> None:
    """
    Remove a scheduled workout from the Coros training calendar.

    plan_id: top-level plan ID (the 'id' field from list_planned_activities).
    id_in_plan: entity's idInPlan value.
    plan_program_id: entity's planProgramId (defaults to id_in_plan if omitted).
    """
    payload = {
        "versionObjects": [{
            "id": id_in_plan,
            "planProgramId": plan_program_id or id_in_plan,
            "planId": plan_id,
            "status": 3,  # 3 = delete
        }],
        "pbVersion": 2,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["schedule_update"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule delete")


async def fetch_exercises(auth: StoredAuth, sport_type: int) -> list[dict]:
    """
    Fetch the exercise catalogue for a given sport type.

    Used to look up strength/conditioning exercises (e.g. sport_type=4 for
    strength) that appear in planned workouts but have no inline detail.
    Returns the raw list of exercise definitions.
    """
    params = {"userId": auth.user_id, "sportType": sport_type}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["exercises"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "exercise list")

    return body.get("data", []) or []


async def fetch_user_profile(auth: StoredAuth) -> dict:
    """Fetch full user profile from Coros /account/query.

    Returns physiological baselines, body metrics, personal info,
    HR zones (all 3 models), pace zones, and cycling power zones.

    Key fields:
      - user_id, nickname, language, country_code, sex, gender
      - stature: height in cm, weight: weight in kg, birthday: YYYYMMDD
      - max_hr, rhr, lthr: heart rate baselines (bpm)
      - ltsp: lactate threshold pace (sec/km), ftp: threshold power (watts)
      - hr_zone_type: default zone model (1=MaxHR, 2=%HRR, 3=%LTHR)
      - unit: 0=metric, 1=imperial
      - activity_count: total lifetime activities
      - zones: dict keyed by int 1/2/3 (MaxHR/%HRR/%LTHR), each 6 boundary entries
      - pace_zones: LTSP pace zone list [{pace, index, ratio}]
      - cycle_power_zones: cycling power zone list [{power, index, ratio}]
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["account_query"],
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "account query")
    data = body.get("data", {})
    zd = data.get("zoneData", {})
    up = data.get("userProfile", {})

    return {
        "user_id": data.get("userId"),
        "nickname": data.get("nickname"),
        "max_hr": data.get("maxHr"),
        "rhr": data.get("rhr"),
        "lthr": zd.get("lthr"),
        "ltsp": zd.get("ltsp"),
        "ftp": zd.get("ftp"),
        "hr_zone_type": data.get("hrZoneType"),
        "stature": data.get("stature"),
        "weight": data.get("weight"),
        "birthday": data.get("birthday"),
        "country_code": data.get("countryCode"),
        "language": up.get("language"),
        "unit": data.get("unit"),
        "sex": data.get("sex"),
        "gender": up.get("gender"),
        "activity_count": (data.get("sportDataSummary") or {}).get("count"),
        "zones": {
            1: zd.get("maxHrZone", []),
            2: zd.get("rhrZone", []),
            3: zd.get("lthrZone", []),
        },
        "pace_zones": zd.get("ltspZone", []),
        "cycle_power_zones": zd.get("cyclePowerZone", []),
    }


# ---------------------------------------------------------------------------
# Mobile token auto-refresh
# ---------------------------------------------------------------------------

async def _refresh_mobile_token(auth: StoredAuth) -> bool:
    """
    Refresh the mobile API token by replaying the stored login payload.

    The stored payload contains AES-encrypted credentials generated during
    coros-mcp auth.  The server accepts replay of the same encrypted payload
    — no nonce or anti-replay protection.

    Returns True and updates auth.mobile_access_token in-place on success.
    """
    if not auth.mobile_login_payload:
        return False

    mobile_base = MOBILE_BASE_URLS.get(auth.region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + MOBILE_LOGIN_ENDPOINT
    headers: dict[str, str] = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=auth.mobile_login_payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()

        if body.get("result") != "0000":
            return False

        token = body.get("data", {}).get("accessToken")
        if not token:
            return False

        auth.mobile_access_token = token
        _save_auth(auth)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Mobile token — lazy acquisition and refresh
# ---------------------------------------------------------------------------

async def _ensure_mobile_token(auth: StoredAuth) -> bool:
    """Ensure auth has a valid mobile access token, acquiring one on-demand if needed.

    Resolution order:
    1. Token already present — nothing to do.
    2. Replay payload stored — try refresh (re-sends the encrypted login payload).
    3. Env credentials available — perform a fresh mobile login.

    Mobile login is deferred until the first call to fetch_sleep() so that
    normal web-token refreshes never disrupt the Coros mobile app session.
    """
    if auth.mobile_access_token:
        return True

    # Try refreshing via the stored encrypted payload (avoids re-entering creds)
    if auth.mobile_login_payload:
        if await _refresh_mobile_token(auth):
            return True

    # Fall back to a fresh mobile login using env credentials
    creds = get_env_credentials()
    if creds is None:
        return False
    email, password, region = creds
    try:
        mobile_token, mobile_payload = await _mobile_login(email, password, region)
        auth.mobile_access_token = mobile_token
        auth.mobile_login_payload = mobile_payload
        _save_auth(auth)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Mobile daily statistics  (shared helper — apieu.coros.com/coros/data/statistic/daily)
# ---------------------------------------------------------------------------

async def _fetch_mobile_daily(
    auth: StoredAuth,
    start_day: str,
    end_day: str,
    data_types: list[int],
) -> list[dict]:
    """
    Fetch daily statistic records from the Coros mobile API for the given
    dataType values.  Handles token acquisition, auto-refresh, and error
    checking.

    Returns the raw ``dayDataList`` entries — each dict has a ``happenDay``
    key plus the requested data blocks for that day.
    """
    if not await _ensure_mobile_token(auth):
        raise ValueError(
            "No mobile API token available. Set COROS_EMAIL and COROS_PASSWORD in .env "
            "for automatic acquisition, or run: coros-mcp auth-mobile"
        )

    mobile_base = MOBILE_BASE_URLS.get(auth.region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + ENDPOINTS["sleep"]
    payload = {
        "allDeviceSleep": 1,
        "dataType": data_types,
        "dataVersion": 0,
        "startTime": int(start_day),
        "endTime": int(end_day),
        "statisticType": 1,
    }

    async def _do_request(token: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                params={"accessToken": token},
                json=payload,
                headers={"Content-Type": "application/json", "accesstoken": token},
            )
            resp.raise_for_status()
            return resp.json()

    body = await _do_request(auth.mobile_access_token)

    if body.get("result") == "1019":  # token expired — auto-refresh once
        if await _refresh_mobile_token(auth):
            body = await _do_request(auth.mobile_access_token)

    if body.get("result") != "0000":
        raise ValueError(f"Coros mobile API error: {body.get('message', 'unknown error')}")

    return body.get("data", {}).get("statisticData", {}).get("dayDataList", [])


# ---------------------------------------------------------------------------
# Sleep data  (mobile API dataType=5)
# ---------------------------------------------------------------------------

async def fetch_sleep(auth: StoredAuth, start_day: str, end_day: str) -> list[SleepRecord]:
    """
    Fetch sleep stage data for a date range from the Coros mobile API.

    Uses dataType=5 on the mobile statistic endpoint.  Returns per-night
    records with deep/light/REM/awake minutes and sleep heart rate.

    start_day / end_day: YYYYMMDD strings.
    """
    raw = await _fetch_mobile_daily(auth, start_day, end_day, [5])

    records: list[SleepRecord] = []
    for item in raw:
        sd = item.get("sleepData", {})
        quality = item.get("performance")
        records.append(SleepRecord(
            date=str(item.get("happenDay", "")),
            total_duration_minutes=sd.get("totalSleepTime"),
            phases=SleepPhases(
                deep_minutes=sd.get("deepTime"),
                light_minutes=sd.get("lightTime"),
                rem_minutes=sd.get("eyeTime"),
                awake_minutes=sd.get("wakeTime"),
                nap_minutes=sd.get("shortSleepTime") or None,
            ),
            avg_hr=sd.get("avgHeartRate"),
            min_hr=sd.get("minHeartRate"),
            max_hr=sd.get("maxHeartRate"),
            quality_score=quality if quality != -1 else None,
        ))
    return sorted(records, key=lambda r: r.date)


# ---------------------------------------------------------------------------
# Daily health  (mobile API dataTypes 1, 3, 4, 5, 22 — all unique to mobile)
# ---------------------------------------------------------------------------

async def fetch_daily_health(
    auth: StoredAuth,
    start_day: str,
    end_day: str,
) -> list[DailyHealthRecord]:
    """
    Fetch combined daily health data from the Coros mobile API.

    Covers data that is NOT available via the Training Hub web API:
      - steps (dataType=3)
      - calories (dataType=1)
      - stress — avg level + duration (dataType=22)
      - sleep stages — deep/light/REM/awake (dataType=5)

    All four data types are fetched in a single API call.

    Returns a list of DailyHealthRecord sorted by date (oldest first).
    """
    raw = await _fetch_mobile_daily(auth, start_day, end_day, [1, 3, 5, 22])

    records: list[DailyHealthRecord] = []
    for item in raw:
        # Sleep (dataType=5)
        sd = item.get("sleepData", {})
        quality = item.get("performance")

        # Stress (dataType=22)
        stress = None
        if "avgStress" in item:
            stress = StressRecord(
                date=str(item.get("happenDay", "")),
                avg_stress=item.get("avgStress"),
                avg_stress_ordinary=item.get("avgStressOrdinary"),
                stress_duration_seconds=item.get("stressDuration"),
                stress_duration_ordinary_seconds=item.get("stressDurationOrdinary"),
            )

        records.append(DailyHealthRecord(
            date=str(item.get("happenDay", "")),
            steps=item.get("step"),                    # dataType=3
            calories=item.get("calorie"),              # dataType=1
            stress=stress,
            sleep_deep_minutes=sd.get("deepTime"),
            sleep_light_minutes=sd.get("lightTime"),
            sleep_rem_minutes=sd.get("eyeTime"),
            sleep_awake_minutes=sd.get("wakeTime"),
            sleep_nap_minutes=sd.get("shortSleepTime") or None,
            sleep_total_minutes=sd.get("totalSleepTime"),
            sleep_avg_hr=sd.get("avgHeartRate"),
            sleep_quality=quality if quality != -1 else None,
        ))

    return sorted(records, key=lambda r: r.date)


# ---------------------------------------------------------------------------
# Public training library  (cn.coros.com/training SSR data)
# ---------------------------------------------------------------------------

PUBLIC_CATALOG_BASE = {
    "cn": "https://cn.coros.com",
    "us": "https://coros.com",
    "eu": "https://eu.coros.com",
}


async def fetch_training_library(region: str = "cn", locale: str = "zh-CN") -> list[TrainingProgram]:
    """Fetch the public COROS training library catalog.

    Fetches the public training page for a CSRF token, then calls the
    /api/training/get-more-workouts endpoint for all category+activity
    combinations to collect the full catalog (workouts + training plans).
    Does not require authentication.
    """
    api_base = PUBLIC_CATALOG_BASE.get(region, PUBLIC_CATALOG_BASE["cn"])
    page_url = f"{api_base}/training"

    browser_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": f"{locale},{locale[:2]};q=0.9",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # Step 1: fetch SSR page to extract CSRF token and cookies
        resp = await client.get(page_url, headers=browser_headers)
        resp.raise_for_status()
        html = resp.text

        idx = html.find("__INITIAL_STATE__")
        if idx == -1:
            raise ValueError("Could not find __INITIAL_STATE__ in page HTML")

        start = html.find("{", idx)
        depth = 0
        for i in range(start, len(html)):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    state = json.loads(html[start:i + 1])
                    break

        csrf = state.get("csrf", "")
        country = state.get("country", region)

        # Collect cookies from the SSR response
        cookies = {}
        for h in resp.headers.get_list("set-cookie"):
            for c in h.split(","):
                if "=" in c:
                    parts = c.split(";")[0].strip().split("=", 1)
                    if len(parts) == 2:
                        cookies[parts[0]] = parts[1]

        api_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "x-csrf-token": csrf,
            "x-country": country or region,
            "Referer": page_url,
            "Origin": api_base,
        }

        # Step 2: paginate through both categories to collect all programs
        all_items: dict[str, dict] = {}
        page_size = 50

        for cat in ("workout", "plan"):
            offset = 0
            while True:
                params = {
                    "category_type": cat,
                    "locale": locale,
                    "offset": str(offset),
                    "limit": str(page_size),
                }
                try:
                    resp2 = await client.get(
                        f"{api_base}/api/training/get-more-workouts",
                        params=params,
                        headers=api_headers,
                        cookies=cookies,
                    )
                    if resp2.status_code != 200:
                        break
                    data = resp2.json()
                    items = data.get("data", {}).get("list", [])
                    pagination = data.get("data", {}).get("pagination", {})
                    for item in items:
                        pid = item["_id"]
                        if pid not in all_items:
                            all_items[pid] = item
                    total = pagination.get("total", 0)
                    offset += len(items)
                    if offset >= total or not items:
                        break
                except Exception:
                    break

    programs = []
    for w in all_items.values():
        category = w.get("category", "workout")
        targets = w.get("workout_target" if category == "workout" else "plan_target", [])
        programs.append(TrainingProgram(
            program_id=w.get("_id", ""),
            linked_id=w.get("linked_id"),
            title=w.get("title", w.get("title_i18n_key", "")),
            description=w.get("content"),
            category=category,
            sport_types=w.get("sport_type", []),
            targets=targets,
            difficulties=w.get("difficulty", []),
            author=w.get("author"),
            author_name=w.get("author_i18n"),
            download_count=w.get("download_count", 0),
            icon_type=w.get("iconType", 1),
            region=w.get("region", 1),
            created_at=w.get("createdAt"),
            updated_at=w.get("updatedAt"),
        ))

    return programs
