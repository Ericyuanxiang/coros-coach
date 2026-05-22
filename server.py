"""
Coros MCP Server — Sleep, HRV, and training data via the unofficial Coros API.

Usage:
    python server.py

MCP config (Claude Code):
    claude mcp add coros \\
      -e COROS_EMAIL=you@example.com \\
      -e COROS_PASSWORD=yourpass \\
      -e COROS_REGION=eu \\
      -- python /path/to/coros-mcp/server.py

Alternatively, create a .env file in the project directory with the same
variables. If COROS_EMAIL and COROS_PASSWORD are set (via env or .env), the
server authenticates automatically on the first request and re-authenticates
transparently whenever the stored token is expired or rejected.
"""

import os
import time
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

import coros_api
from coros_api import TOKEN_TTL_MS

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

mcp = FastMCP("coros-mcp")


async def _get_auth():
    """Return stored auth, auto-logging in from env vars if the token is missing/expired."""
    auth = coros_api.get_stored_auth()
    if auth is None:
        auth = await coros_api.try_auto_login()
    return auth


async def _run_with_auth(fn, auth, *args, **kwargs):
    """Call fn(auth, …). On exception, re-login from env vars and retry once."""
    try:
        return await fn(auth, *args, **kwargs)
    except Exception:
        new_auth = await coros_api.try_auto_login()
        if new_auth is None:
            raise
        return await fn(new_auth, *args, **kwargs)


def _tool_error(exc: Exception, **extra) -> dict:
    """Build a categorized error dict for MCP tool return values.

    Distinguishes HTTP errors, network failures, API errors, and unexpected
    internal errors so callers can handle them differently.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return {
            "error": f"Coros server returned HTTP {exc.response.status_code}",
            "error_type": "http",
            **extra,
        }
    if isinstance(exc, httpx.ConnectError):
        return {
            "error": "Cannot connect to Coros server — check network",
            "error_type": "network",
            **extra,
        }
    if isinstance(exc, httpx.TimeoutException):
        return {
            "error": "Coros server timed out — try again later",
            "error_type": "timeout",
            **extra,
        }
    if isinstance(exc, ValueError):
        return {
            "error": str(exc),
            "error_type": "api_error",
            **extra,
        }
    return {
        "error": str(exc),
        "error_type": "internal",
        **extra,
    }


def _summarize_steps(steps: list[dict]) -> tuple[float, int]:
    """Return (total_minutes, steps_count) for a workout step list."""
    total_minutes = 0.0
    steps_count = 0
    for s in steps:
        if "repeat" in s:
            sub_mins = sum(sub["duration_minutes"] for sub in s["steps"])
            total_minutes += sub_mins * s["repeat"]
            steps_count += 1 + len(s["steps"])
        else:
            total_minutes += s["duration_minutes"]
            steps_count += 1
    return total_minutes, steps_count


# ---------------------------------------------------------------------------
# Tool: authenticate_coros
# ---------------------------------------------------------------------------

@mcp.tool()
async def authenticate_coros(
    email: str,
    password: str,
    region: str = "eu",
) -> dict:
    """
    Authenticate with the Coros Training Hub API and store the access token.

    Parameters
    ----------
    email : str
        Coros account email address.
    password : str
        Coros account password (plain text — hashed with MD5 before sending).
    region : str
        "eu" (default) or "us".  EU users must use "eu" — tokens are
        region-bound (EU tokens only work on teameuapi.coros.com).

    Returns
    -------
    dict with keys: authenticated, user_id, region, message
    """
    try:
        auth = await coros_api.login(email, password, region)
        return {
            "authenticated": True,
            "user_id": auth.user_id,
            "region": auth.region,
            "message": "Token stored securely (keyring or encrypted file)",
        }
    except Exception as exc:
        return _tool_error(exc, authenticated=False)


# ---------------------------------------------------------------------------
# Tool: authenticate_coros_mobile
# ---------------------------------------------------------------------------

@mcp.tool()
async def authenticate_coros_mobile(
    email: str,
    password: str,
    region: str = "eu",
) -> dict:
    """
    Authenticate with the Coros mobile API only and store the mobile token.

    This is needed for sleep data (deep/light/REM/awake phases) which is
    only available through the mobile API (apieu.coros.com), not the
    Training Hub web API.

    Parameters
    ----------
    email : str
        Coros account email address.
    password : str
        Coros account password (plain text — encrypted before sending).
    region : str
        "eu" (default) or "us".

    Returns
    -------
    dict with keys: authenticated, region, message
    """
    try:
        auth = await coros_api.login_mobile(email, password, region)
        return {
            "authenticated": True,
            "user_id": auth.user_id or "(web auth required for user_id)",
            "region": auth.region,
            "message": "Mobile token stored. Sleep data is now available.",
        }
    except Exception as exc:
        return _tool_error(exc, authenticated=False)


# ---------------------------------------------------------------------------
# Tool: check_coros_auth
# ---------------------------------------------------------------------------

@mcp.tool()
async def check_coros_auth() -> dict:
    """
    Check whether valid Coros access tokens are stored locally.

    Returns
    -------
    dict with keys: authenticated, user_id, region, expires_in_hours,
    mobile_authenticated, mobile_token_status
    """
    auth = coros_api.get_stored_auth()
    if auth is None:
        return {
            "authenticated": False,
            "mobile_authenticated": False,
            "message": "No valid token found. Call authenticate_coros first.",
        }

    age_ms = int(time.time() * 1000) - auth.timestamp
    remaining_ms = TOKEN_TTL_MS - age_ms
    remaining_hours = round(remaining_ms / 3_600_000, 1)

    has_mobile = bool(auth.mobile_access_token)
    if has_mobile:
        mobile_status = "present (refresh via stored payload)"
    elif auth.mobile_login_payload:
        mobile_status = "expired (can auto-refresh)"
    else:
        mobile_status = "missing (run auth or auth-mobile)"

    return {
        "authenticated": bool(auth.access_token),
        "user_id": auth.user_id,
        "region": auth.region,
        "expires_in_hours": remaining_hours,
        "mobile_authenticated": has_mobile,
        "mobile_token_status": mobile_status,
    }


# ---------------------------------------------------------------------------
# Tool: get_dashboard
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_dashboard() -> dict:
    """
    Fetch the Coros dashboard snapshot for quick athlete-state assessment.

    Returns current HRV, sleep quality, training readiness, recent activity
    summaries, and fitness trends — without date parameters. Uses the
    /dashboard/query endpoint which always returns recent data (typically
    last 7 days + today).

    Returns
    -------
    dict with the full dashboard data payload.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        data = await _run_with_auth(coros_api.fetch_dashboard, auth)
        return data
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_daily_metrics
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_training_analysis(
    weeks: int = 4,
    include_daily: bool = True,
    include_summary: bool = False,
) -> dict:
    """
    Fetch the full Coros training analysis ("数据分析") for a configurable
    time range (up to 24 weeks).

    Merges data from /analyse/dayDetail/query (configurable range, 35 fields
    per day including HRV) and /analyse/query (fixed 84-day window, 9 sections
    including records, summaries, and distributions).

    Parameters
    ----------
    weeks : int
        Number of weeks to fetch (1–24). Default: 4.
    include_daily : bool
        Include daily_records (35 fields per day). Default True.
    include_summary : bool
        Include summary_info (10 distribution charts — large). Default False.

    Returns
    -------
    dict always containing:

      week_list (list)
          12 weekly summaries: firstDayOfWeek, trainingLoad,
          recomendTlMin, recomendTlMax.

      records (dict)
          Personal records: distanceRecord, durationRecord, tlRecord.

      sport_statistic (list)
          Per-sport aggregated stats: sportType, count, distance, duration,
          trainingLoad, avgHeartRate, avgPace.

      tl_intensity (dict)
          Weekly training load intensity breakdown: periodLowPct,
          periodMediumPct, periodHighPct over 6 weeks.

      sport_data_summary (dict)
          Total activity count and model validity status.

      training_week_stages (list)
          Training phase stages (may be empty).

    Plus when requested:

      daily_records (list[dict]) — if include_daily=True
          Per-day 35-field records: date, avg_sleep_hrv, baseline,
          interval_list, rhr, test_rhr, lthr, training_load,
          training_load_target, training_load_ratio_state, t7d, t28d,
          recomend_tl_max/min, tired_rate, tib, ati, cti, performance,
          distance, duration, vo2max, stamina_level, ltsp, etc.

      summary_info (dict) — if include_summary=True
          10 distribution charts: disAreaList, timeAreaList, tlAreaList,
          distanceCountAreaList, distanceTimeAreaList, distanceTlAreaList,
          hrDisAreaList, hrTimeAreaList, hrTlAreaList, recomendTlInDays.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    weeks = max(1, min(weeks, 24))
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=weeks)
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    try:
        data = await _run_with_auth(coros_api.fetch_training_analysis, auth, start_day, end_day)
        if not include_daily:
            data.pop("daily_records", None)
        if not include_summary:
            data.pop("summary_info", None)
        return data
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_sleep_data
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_sleep_data(weeks: int = 4) -> dict:
    """
    Fetch nightly sleep data from Coros for a configurable time range.

    Returns per-night sleep stage breakdown (deep, light, REM, awake) and
    sleep heart rate for each night.  Data comes from the Coros mobile API
    (apieu.coros.com) which is separate from the Training Hub web API.

    Parameters
    ----------
    weeks : int
        Number of weeks to fetch (1–52). Default: 4.

    Returns
    -------
    dict with keys: records (list of nightly records), count, date_range
    Each record contains:
      - date: YYYYMMDD (the morning date — sleep started the night before)
      - total_duration_minutes: total sleep in minutes
      - phases.deep_minutes: deep sleep
      - phases.light_minutes: light sleep
      - phases.rem_minutes: REM sleep
      - phases.awake_minutes: time awake during the night
      - phases.nap_minutes: daytime nap time (if any)
      - avg_hr: average heart rate during sleep
      - min_hr: minimum heart rate during sleep
      - max_hr: maximum heart rate during sleep
      - quality_score: sleep quality score (null if not computed)
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "records": []}

    weeks = max(1, min(weeks, 52))
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=weeks)
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    try:
        records = await _run_with_auth(coros_api.fetch_sleep, auth, start_day, end_day)
        return {
            "records": [r.model_dump() for r in records],
            "count": len(records),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return _tool_error(exc, records=[])


# ---------------------------------------------------------------------------
# Tool: get_daily_health
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_daily_health(weeks: int = 4) -> dict:
    """
    Fetch daily health data that is only available via the Coros mobile API.

    This covers data NOT present in get_training_analysis or get_dashboard:
      - steps: daily step count
      - calories: total daily calorie expenditure
      - stress: avg_stress level + stress_duration in seconds
      - sleep stages: deep, light, REM, awake minutes (same as get_sleep_data)

    All four data types are fetched in a single mobile API call.

    Parameters
    ----------
    weeks : int
        Number of weeks to fetch (1–52). Default: 4.

    Returns
    -------
    dict with keys: records (list), count, date_range
    Each record contains:
      - date: YYYYMMDD
      - steps: daily steps
      - calories: total daily calories
      - stress.avg_stress: average stress level
      - stress.stress_duration_seconds: time under stress
      - sleep_deep_minutes / sleep_light_minutes / sleep_rem_minutes / sleep_awake_minutes
      - sleep_total_minutes / sleep_avg_hr / sleep_quality
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "records": []}

    weeks = max(1, min(weeks, 52))
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=weeks)
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    try:
        records = await _run_with_auth(coros_api.fetch_daily_health, auth, start_day, end_day)
        return {
            "records": [r.model_dump() for r in records],
            "count": len(records),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return _tool_error(exc, records=[])


# ---------------------------------------------------------------------------
# Tool: list_activities
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_activities(
    start_day: str,
    end_day: str,
    page: int = 1,
    size: int = 30,
) -> dict:
    """
    List Coros activities for a date range.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.
    page : int
        Page number (default 1).
    size : int
        Results per page (default 30, max 100).

    Returns
    -------
    dict with keys: activities (list), total_count, page
    Each activity contains: activity_id, name, sport_type, sport_name,
    start_time, end_time, duration_seconds, distance_meters, avg_hr, max_hr,
    calories, training_load, avg_power, normalized_power, elevation_gain
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "activities": []}
    try:
        activities, total = await _run_with_auth(coros_api.fetch_activities, auth, start_day, end_day, page, size)
        return {
            "activities": [a.model_dump() for a in activities],
            "total_count": total,
            "page": page,
        }
    except Exception as exc:
        return _tool_error(exc, activities=[])


# ---------------------------------------------------------------------------
# Tool: list_sport_types
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_sport_types() -> dict:
    """
    List all sport types supported by Coros with their IDs and names.

    Useful for finding the correct sport_type ID when creating workouts
    (create_workout, create_run_workout) or filtering activities.

    Returns
    -------
    dict with keys: sport_types (list), count
    Each sport type contains sportType, sportName, and other metadata.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "sport_types": []}
    try:
        items = await _run_with_auth(coros_api.fetch_sport_types, auth)
        return {"sport_types": items, "count": len(items)}
    except Exception as exc:
        return _tool_error(exc, sport_types=[])


# ---------------------------------------------------------------------------
# Tool: get_activity_detail
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_activity_detail(activity_id: str, sport_type: int = 0) -> dict:
    """
    Fetch full detail for a single Coros activity.

    Parameters
    ----------
    activity_id : str
        The activity ID (labelId) from list_activities.
    sport_type : int
        Sport type ID from list_activities (e.g. 200=Road Bike, 201=Indoor Cycling,
        100=Running). Required for the API call to succeed.

    Returns
    -------
    dict with full activity data including laps, HR zones, power metrics,
    elevation, and all available sport-specific fields.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _run_with_auth(coros_api.fetch_activity_detail, auth, activity_id, sport_type)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: list_workouts
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_workouts() -> dict:
    """
    List all saved workout programs in the Coros account.

    Returns
    -------
    dict with keys: workouts (list), count
    Each workout contains: id, name, sport_type, sport_name,
    estimated_time_seconds, estimated_distance, training_load,
    create_timestamp, exercise_count, exercises (list of steps with
    name, duration_seconds, power_low_w, power_high_w, intensity_type,
    hr_type, intensity_percent, intensity_percent_extend, overview,
    rest_seconds, sort_no, sets)
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "workouts": []}
    try:
        workouts = await _run_with_auth(coros_api.fetch_workouts, auth)
        return {"workouts": workouts, "count": len(workouts)}
    except Exception as exc:
        return _tool_error(exc, workouts=[])


# ---------------------------------------------------------------------------
# Tool: create_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_workout(
    name: str,
    steps: list[dict],
    sport_type: int = 2,
) -> dict:
    """
    Create a new structured workout in the Coros account.

    The workout appears in the Coros app under Workouts and can be synced
    to the watch for guided execution.

    Parameters
    ----------
    name : str
        Workout name (e.g. "Z2 Erholung 60min").
    steps : list[dict]
        List of workout steps. Each step is either a plain step or a repeat group.

        Plain step:
          - name (str): step label, e.g. "10:00 Einfahren"
          - duration_minutes (float): step duration in minutes
          - power_low_w (int): lower power target in watts
          - power_high_w (int): upper power target in watts

        Repeat group (for intervals):
          - repeat (int): number of repetitions
          - steps (list[dict]): sub-steps (same format as plain steps)

        Example:
          [
            {"name": "Warm-up", "duration_minutes": 10, "power_low_w": 148, "power_high_w": 192},
            {"repeat": 3, "steps": [
              {"name": "Sweetspot", "duration_minutes": 10, "power_low_w": 265, "power_high_w": 285},
              {"name": "Recovery", "duration_minutes": 3, "power_low_w": 150, "power_high_w": 175},
            ]},
            {"name": "Cool-down", "duration_minutes": 10, "power_low_w": 100, "power_high_w": 165},
          ]
    sport_type : int
        Sport type ID. Default 2 = Indoor Cycling (Rollen).
        Use 200 for Road Bike (outdoor), 201 for Indoor Cycling (alt).

    Returns
    -------
    dict with keys: workout_id, name, total_minutes, steps_count, message
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        workout_id = await _run_with_auth(coros_api.create_workout, auth, name, steps, sport_type)
        total_minutes, steps_count = _summarize_steps(steps)
        return {
            "workout_id": workout_id,
            "name": name,
            "total_minutes": total_minutes,
            "steps_count": steps_count,
            "message": "Workout created. Open Coros app → Workouts to sync to watch.",
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: delete_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def delete_workout(
    workout_id: str,
) -> dict:
    """
    Delete a workout program from the Coros account.

    Parameters
    ----------
    workout_id : str
        The workout ID to delete (from list_workouts).

    Returns
    -------
    dict with keys: deleted, workout_id, message
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        await _run_with_auth(coros_api.delete_workout, auth, workout_id)
        return {
            "deleted": True,
            "workout_id": workout_id,
            "message": "Workout deleted.",
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: list_planned_activities
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_planned_activities(
    start_day: str,
    end_day: str,
) -> dict:
    """
    List planned (scheduled) activities from the Coros training calendar.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.

    Returns
    -------
    dict with keys: activities (list of raw scheduled items), count, date_range
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "activities": []}
    try:
        items = await _run_with_auth(coros_api.fetch_schedule, auth, start_day, end_day)
        return {
            "activities": items,
            "count": len(items),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return _tool_error(exc, activities=[])


# ---------------------------------------------------------------------------
# Tool: get_training_summary
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_training_summary(
    start_day: str,
    end_day: str,
) -> dict:
    """
    Get training volume summary from the Coros training calendar.

    Returns aggregated totals (duration, training load, session count)
    over a date range without downloading full workout details.  Uses
    /training/schedule/querysum — a lighter alternative to the detailed
    schedule query.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.

    Returns
    -------
    dict with keys: data (the aggregate payload), date_range
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        data = await _run_with_auth(coros_api.fetch_schedule_summary, auth, start_day, end_day)
        return {
            "data": data,
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: schedule_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def schedule_workout(
    workout_id: str,
    happen_day: str,
    sort_no: int = 1,
) -> dict:
    """
    Add an existing workout from the library to the Coros training calendar.

    Parameters
    ----------
    workout_id : str
        ID of the workout to schedule (from list_workouts or create_workout).
    happen_day : str
        Date in YYYYMMDD format.
    sort_no : int
        Order within the day if multiple workouts are scheduled (default 1).

    Returns
    -------
    dict with keys: scheduled, workout_id, happen_day
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        await _run_with_auth(coros_api.schedule_workout, auth, workout_id, happen_day, sort_no)
        return {"scheduled": True, "workout_id": workout_id, "happen_day": happen_day}
    except Exception as exc:
        return _tool_error(exc, scheduled=False)


# ---------------------------------------------------------------------------
# Tool: remove_scheduled_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def remove_scheduled_workout(
    plan_id: str,
    id_in_plan: str,
    plan_program_id: str = "",
) -> dict:
    """
    Remove a scheduled workout from the Coros training calendar.

    Parameters
    ----------
    plan_id : str
        Top-level plan ID — the 'id' field returned by list_planned_activities.
    id_in_plan : str
        The entity's idInPlan value from list_planned_activities.
    plan_program_id : str
        The entity's planProgramId (leave empty to use id_in_plan).

    Returns
    -------
    dict with keys: removed, plan_id, id_in_plan
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        await _run_with_auth(
            coros_api.remove_scheduled_workout, auth, plan_id, id_in_plan, plan_program_id or None
        )
        return {"removed": True, "plan_id": plan_id, "id_in_plan": id_in_plan}
    except Exception as exc:
        return _tool_error(exc, removed=False)


# ---------------------------------------------------------------------------
# Tool: create_strength_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_strength_workout(
    name: str,
    exercises: list[dict],
    sets: int = 1,
) -> dict:
    """
    Create a new structured strength workout program.

    Parameters
    ----------
    name : str
        Workout name.
    exercises : list of dicts, each with:
        - origin_id (str): exercise catalogue ID from list_exercises
        - name (str): T-code name (e.g. "T1061")
        - overview (str): sid_ key (e.g. "sid_strength_squats")
        - target_type (int): 2=time in seconds, 3=reps
        - target_value (int): number of seconds or reps
        - rest_seconds (int): rest after this exercise (default 60)
    sets : int
        Number of circuit repetitions (default 1).

    Returns
    -------
    dict with keys: workout_id, name, sets, exercise_count
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        workout_id = await _run_with_auth(coros_api.create_strength_workout, auth, name, exercises, sets)
        return {
            "workout_id": workout_id,
            "name": name,
            "sets": sets,
            "exercise_count": len(exercises),
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: list_exercises
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_exercises(sport_type: int = 4) -> dict:
    """
    List the exercise catalogue for a given sport type.

    Useful for resolving strength/conditioning exercises (sport_type=4)
    that appear in planned workouts by name and ID.

    Parameters
    ----------
    sport_type : int
        Sport type ID. Default 4 = Strength.

    Returns
    -------
    dict with keys: exercises (list), count, sport_type
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "exercises": []}
    try:
        items = await _run_with_auth(coros_api.fetch_exercises, auth, sport_type)
        return {"exercises": items, "count": len(items), "sport_type": sport_type}
    except Exception as exc:
        return _tool_error(exc, exercises=[])


# ---------------------------------------------------------------------------
# Tool: create_run_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_run_workout(
    name: str,
    steps: list[dict],
    sport_type: int = 1,
    hr_type: int = 3,
    intensity_type: int = 2,
    value_type: int | None = None,
) -> dict:
    """
    Create a running workout with heart rate and pace targets.

    Zone mode (hr_low 1-6): auto-looks up bpm from your COROS zone tables
    via /account/query, sets intensityPercent (zone ratio x1000, e.g. 59000)
    and marks isIntensityPercent=True so the watch displays percentage labels.
    hr_type selects the zone model:
      1=MaxHR, 2=%HRR (储备心率), 3=%LTHR (乳酸阈值, default).

    BPM mode (hr_low > 6): absolute bpm values passed directly (no
    intensityPercent auto-generation).

    Parameters
    ----------
    name : str
        Workout name (e.g. "Z2 耐力跑 60min").
    steps : list[dict]
        List of workout steps. Each step is either a plain step or a repeat group.

        Plain step:
          - name (str): step label
          - duration_minutes (float): step duration in minutes
          - hr_low (int): zone 1-6, or absolute bpm if > 6
          - hr_high (int, optional): zone 1-6, or absolute bpm
          - pace_low (int, optional): lower pace target in sec/km
          - pace_high (int, optional): upper pace target in sec/km

        Repeat group (for intervals):
          - repeat (int): number of repetitions
          - steps (list[dict]): sub-steps (same format as plain steps)

        Zone mode example:
          [
            {"name": "10:00 热身", "duration_minutes": 10, "hr_low": 1},
            {"name": "40:00 有氧耐力", "duration_minutes": 40, "hr_low": 2},
            {"name": "10:00 冷却", "duration_minutes": 10, "hr_low": 1},
          ]

        Interval example (5×3min VO2max):
          [
            {"name": "15:00 热身", "duration_minutes": 15, "hr_low": 1},
            {"repeat": 5, "steps": [
              {"name": "3:00 VO2max", "duration_minutes": 3, "hr_low": 5},
              {"name": "3:00 恢复", "duration_minutes": 3, "hr_low": 1},
            ]},
            {"name": "10:00 冷却", "duration_minutes": 10, "hr_low": 1},
          ]
    sport_type : int
        Sport type ID. Default 1 = Running.
        Use 102 for Trail Running, 103 for Track Running.
    hr_type : int
        Zone model: 1=%MaxHR, 2=%HRR (储备心率), 3=%LTHR (乳酸阈值, default).
        Only used in zone mode (hr_low 1-6).
    intensity_type : int
        Intensity calculation model. Default 2 = Heart Rate.
          2 = Heart Rate   — with hr_type controls display name:
              hr_type=1 → "%最大心率", hr_type=2 → "%储备心率", hr_type=3 → "%乳酸阈心率"
              Pass value_type=1 for absolute "心率" display instead.
          3 = Pace         (配速, use with pace_low/pace_high in sec/km)
          6 = Power        (功率, use with power targets in watts)
          7 = Cadence      (步频, use with cadence targets in spm)
          8 = Equivalent Pace (等强配速, pace-based equivalent-intensity model)
    value_type : int, optional
        1 = absolute display ("心率" / "配速" / "功率" / "步频" / "等强配速")
        2 = percentage display ("%最大心率" / "%储备心率" / "%乳酸阈心率" / "%乳酸阈配速" / "等强阈值配速")
        Default: 2 for HR types (intensity_type=2), 1 for pace/power/cadence types.
        Auto-applied via isIntensityPercent + intensityPercent in exercise payload.

    Returns
    -------
    dict with keys: workout_id, name, total_minutes, steps_count, message
    """
    VALID_INTENSITY_TYPES = {2, 3, 6, 7, 8}
    if intensity_type not in VALID_INTENSITY_TYPES:
        return {
            "error": f"intensity_type {intensity_type} is not a valid COROS intensity model. "
                     f"Valid: 2=Heart Rate (with hr_type controls %%MaxHR/%%HRR/%%LTHR display), "
                     f"3=Pace, 6=Power, 7=Cadence, 8=Equivalent Pace."
        }
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        workout_id = await _run_with_auth(coros_api.create_run_workout, auth, name, steps, sport_type, hr_type, intensity_type, value_type)
        total_minutes, steps_count = _summarize_steps(steps)
        return {
            "workout_id": workout_id,
            "name": name,
            "total_minutes": f"{int(total_minutes // 60)}:{int(total_minutes % 60):02d}",
            "steps_count": steps_count,
            "message": "Running workout created. Open Coros app → Workouts to sync to watch.",
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_user_profile
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_user_profile() -> dict:
    """Fetch full user profile with all zone tables from Coros.

    Calls /account/query to retrieve physiological baselines, body
    metrics, personal info, HR zones, pace zones, and power zones.

    Returns
    -------
    dict with keys:
      - user_id, nickname, language, country_code, sex, gender
      - stature: height in cm, weight: weight in kg, birthday: YYYYMMDD
      - max_hr, rhr, lthr: heart rate baselines (bpm)
      - ltsp: lactate threshold pace (sec/km), ftp: threshold power (watts)
      - hr_zone_type: default zone model (1=MaxHR, 2=%HRR, 3=%LTHR)
      - unit: 0=metric, 1=imperial
      - activity_count: total lifetime activities
      - zones: HR zone boundaries keyed by 1/2/3 (MaxHR/%HRR/%LTHR)
      - pace_zones: LTSP pace zone list [{pace, index, ratio}]
      - cycle_power_zones: cycling power zone list [{power, index, ratio}]
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        data = await _run_with_auth(coros_api.fetch_user_profile, auth)
        return data
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_training_library
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_training_library(region: str = "cn", locale: str = "zh-CN") -> dict:
    """Browse the official COROS public training library.

    Returns a catalog of training programs (workouts and training plans)
    created by COROS coaches and elite athletes.  This data is publicly
    accessible — no authentication required.

    The catalog includes for each program:
      - program_id: public catalog identifier
      - linked_id: Training Hub program ID (use with import_training_program)
      - title: localized display name
      - description: localized description/workout notes
      - category: "workout" for single workouts, "plan" for multi-week plans
      - sport_types: e.g. ["run", "cycling", "strength"]
      - targets: training focus (base_workout, tempo, ftp, threshold, etc.)
      - difficulties: ["beginner", "intermediate", "advanced"]
      - author / author_name: creator info
      - download_count: popularity metric

    Parameters
    ----------
    region : str
        Region code: "cn" (China), "us" (US), or "eu" (Europe).
        Default: "cn".
    locale : str
        Language for localized text.  "zh-CN" for Chinese, "en-US" for
        English, "de" for German, etc.  Default: "zh-CN".

    Returns
    -------
    dict with keys: programs (list of TrainingProgram), count, region, locale
    """
    try:
        programs = await coros_api.fetch_training_library(region, locale)
        return {
            "programs": [p.model_dump() for p in programs],
            "count": len(programs),
            "region": region,
            "locale": locale,
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
