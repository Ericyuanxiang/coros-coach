"""
Coros AI Coach MCP Server — 高驰AI教练

Usage:
    python server.py

MCP config (Claude Code):
    claude mcp add coros \\
      -e COROS_EMAIL=you@example.com \\
      -e COROS_PASSWORD=yourpass \\
      -e COROS_REGION=eu \\
      -- python /path/to/coros-ai-coach/server.py

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

mcp = FastMCP("coros-ai-coach")

# Sport types that support file download (from COROS activityExportFileTypes.json)
_SUPPORTED_DOWNLOAD_SPORT_TYPES = frozenset({
    100, 101, 102, 103, 104, 105,      # Running variants
    200, 201, 202, 203, 204, 205, 299,  # Cycling variants
    300, 301,                           # Swimming
    400, 401, 402,                      # Strength/Training
    500, 501, 502, 503,                 # Cardio
    700, 701, 702, 704, 705, 706, 707, 708, 709, 710, 711, 712, 713, 714, 715,  # Outdoor
    800, 801, 802,                      # Indoor
    900, 901, 902, 903, 904, 905, 906,  # Water sports
    1000, 1001, 1002, 1003, 1004, 1005, 1006,  # Winter sports
    1100, 1101,                         # Multisport
    1200,                               # Other
    9800, 9900,                         # System
    10000, 10001, 10002, 10003,         # More
})


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
# Tool: get_team_activities
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_team_activities(team_id: str = "", start_day: str = "", end_day: str = "", size: int = 20) -> dict:
    """Fetch the team activity feed.

    Parameters
    ----------
    team_id : str
        Team ID (default: auto-detect primary team).
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.
    size : int
        Number of activities to return (default 20).

    Returns
    -------
    dict with keys: team_activities (list), count.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "team_activities": []}
    try:
        items = await _run_with_auth(coros_api.fetch_activity_team_query, auth, team_id, start_day, end_day, size)
        return {"team_activities": [a.model_dump() if hasattr(a, "model_dump") else a for a in (items or [])], "count": len(items or [])}
    except Exception as exc:
        return _tool_error(exc, team_activities=[])


# ---------------------------------------------------------------------------
# Tool: list_sport_types
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_sport_types() -> dict:
    """
    List all sport types supported by Coros with their IDs and names.

    Useful for finding the correct sport_type ID when creating workouts
    create_workout (cycling/running/strength) or filtering activities.

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
# Tool: import_fit_file
# ---------------------------------------------------------------------------

@mcp.tool()
async def import_fit_file(file_path: str) -> dict:
    """Import a FIT file as a new activity.

    Parameters
    ----------
    file_path : str
        Absolute path to the .fit file on disk.

    Returns
    -------
    dict with imported activity data (id, sportType, etc.).
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    try:
        return await _run_with_auth(coros_api.fetch_fit_import, auth, file_path)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: delete_fit_import
# ---------------------------------------------------------------------------

@mcp.tool()
async def delete_fit_import(import_id: str) -> dict:
    """Delete a previously imported FIT file activity.

    Parameters
    ----------
    import_id : str
        The ID of the imported FIT session.

    Returns
    -------
    dict confirming deletion.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _run_with_auth(coros_api.fetch_fit_delete, auth, import_id)
    except Exception as exc:
        return _tool_error(exc)


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
# Tool: get_activity_file — download URL for FIT/GPX/TCX/KML/CSV activity file
# ---------------------------------------------------------------------------

@mcp.tool()
async def download_activity_file(activity_id: str, sport_type: int, file_type: int = 4, output_dir: str = "") -> dict:
    """
    Download an activity file (FIT/GPX/TCX/KML/CSV) to local disk.

    Saves the file and returns the local path.

    Parameters
    ----------
    activity_id : str
        The activity ID (labelId) from list_activities.
    sport_type : int
        Sport type ID (e.g. 100=Running, 200=Road Bike, 201=Indoor Cycling).
    file_type : int
        0=CSV, 1=GPX, 2=KML, 3=TCX, 4=FIT (default 4).
    output_dir : str
        Directory to save the file (default: system temp directory).

    Returns
    -------
    dict with keys: filePath (str), fileType (str), sizeBytes (int).
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    if sport_type not in _SUPPORTED_DOWNLOAD_SPORT_TYPES:
        return {"error": f"File download is not supported for sport type {sport_type}."}
    try:
        return await _run_with_auth(coros_api.fetch_activity_download, auth, activity_id, sport_type, file_type, output_dir)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: update_activity
# ---------------------------------------------------------------------------

@mcp.tool()
async def update_activity(activity_id: str, name: str = "", note: str = "") -> dict:
    """Update an activity's metadata (name, note).

    Parameters
    ----------
    activity_id : str
        The activity labelId from list_activities.
    name : str
        New display name for the activity.
    note : str
        New note/description for the activity.

    Returns
    -------
    dict with updated activity data.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        updates = {}
        if name:
            updates["name"] = name
        if note:
            updates["note"] = note
        if not updates:
            return {"error": "No fields to update. Provide name or note."}
        return await _run_with_auth(coros_api.fetch_update_activity, auth, activity_id, updates)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: delete_activity
# ---------------------------------------------------------------------------

@mcp.tool()
async def delete_activity(activity_id: str) -> dict:
    """Delete an activity by ID.

    Parameters
    ----------
    activity_id : str
        The activity labelId from list_activities.

    Returns
    -------
    dict confirming deletion.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _run_with_auth(coros_api.fetch_delete_activity, auth, activity_id)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: list_workouts
# ---------------------------------------------------------------------------

@mcp.tool()
async def manage_workout(
    action: str,
    workout_id: str = "",
    workout_data: dict | None = None,
) -> dict:
    """Unified workout management — list, detail, update, copy, delete.

    Parameters
    ----------
    action : str
        "list" — return all saved workout programs.
        "detail" — get full workout detail by workout_id.
        "update" — modify a workout (requires workout_data with id).
        "delete" — delete a workout by workout_id.
    workout_id : str
        Workout ID (required for detail/copy/delete).
    workout_data : dict
        Full workout JSON (required for update).

    Returns
    -------
    dict with workout data, list, or confirmation.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    valid_actions = {"list", "detail", "update", "delete"}
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Use one of: {', '.join(sorted(valid_actions))}."}

    try:
        if action == "list":
            workouts = await _run_with_auth(coros_api.fetch_workouts, auth)
            return {"workouts": workouts, "count": len(workouts)}

        elif action == "detail":
            if not workout_id:
                return {"error": "workout_id is required for detail action."}
            return await _run_with_auth(coros_api.fetch_program_detail, auth, workout_id)

        elif action == "update":
            if not workout_data:
                return {"error": "workout_data is required for update action."}
            return await _run_with_auth(coros_api.update_workout, auth, workout_data)

        elif action == "delete":
            if not workout_id:
                return {"error": "workout_id is required for delete action."}
            await _run_with_auth(coros_api.delete_workout, auth, workout_id)
            return {"deleted": True, "workout_id": workout_id, "message": "Workout deleted."}
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: create_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_workout(
    workout_type: str,
    name: str,
    steps: list[dict] | None = None,
    exercises: list[dict] | None = None,
    sport_type: int | None = None,
    hr_type: int = 3,
    intensity_type: int = 2,
    value_type: int | None = None,
    sets: int = 1,
) -> dict:
    """Create a structured workout in the Coros account. Supports cycling, running, and strength.

    Parameters
    ----------
    workout_type : str
        "cycling", "running", or "strength".
    name : str
        Workout name (e.g. "Z2 Endurance 60min").
    steps : list[dict], required for cycling/running
        List of workout steps. Each step is a plain step or a repeat group.

        Cycling step fields: name, duration_minutes, power_low_w, power_high_w
        Running step fields: name, duration_minutes, hr_low (zone 1-6 or bpm),
          hr_high (optional), pace_low (optional sec/km), pace_high (optional)

        Repeat group: {"repeat": N, "steps": [...]}
    exercises : list[dict], required for strength
        Each with: origin_id, name, overview, target_type (2=time, 3=reps),
        target_value, rest_seconds.
    sport_type : int, optional
        Cycling: 2=Indoor (default), 200=Road Bike.
        Running: 1=Running (default), 102=Trail, 103=Track.
    hr_type : int, running only
        Zone model: 1=MaxHR, 2=%HRR, 3=%LTHR (default).
    intensity_type : int, running only
        2=Heart Rate (default), 3=Pace, 6=Power, 7=Cadence, 8=Equivalent Pace.
    value_type : int, running only
        1=absolute display, 2=percentage display.
    sets : int, strength only
        Number of circuit repetitions (default 1).

    Returns
    -------
    dict with: workout_id, name, message
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        if workout_type == "cycling":
            sport = sport_type if sport_type is not None else 2
            workout_id = await _run_with_auth(coros_api.create_workout, auth, name, steps or [], sport)
            total_minutes, steps_count = _summarize_steps(steps or [])
            return {
                "workout_id": workout_id,
                "name": name,
                "total_minutes": total_minutes,
                "steps_count": steps_count,
                "message": "Workout created. Open Coros app → Workouts to sync to watch.",
            }
        elif workout_type == "running":
            sport = sport_type if sport_type is not None else 1
            VALID_INTENSITY_TYPES = {2, 3, 6, 7, 8}
            if intensity_type not in VALID_INTENSITY_TYPES:
                return {
                    "error": f"intensity_type {intensity_type} is not valid. "
                             f"Valid: 2=Heart Rate, 3=Pace, 6=Power, 7=Cadence, 8=Equivalent Pace."
                }
            workout_id = await _run_with_auth(
                coros_api.create_run_workout, auth, name, steps or [], sport, hr_type, intensity_type, value_type,
            )
            total_minutes, steps_count = _summarize_steps(steps or [])
            return {
                "workout_id": workout_id,
                "name": name,
                "total_minutes": f"{int(total_minutes // 60)}:{int(total_minutes % 60):02d}",
                "steps_count": steps_count,
                "message": "Running workout created. Open Coros app → Workouts to sync to watch.",
            }
        elif workout_type == "strength":
            workout_id = await _run_with_auth(coros_api.create_strength_workout, auth, name, exercises or [], sets)
            return {
                "workout_id": workout_id,
                "name": name,
                "sets": sets,
                "exercise_count": len(exercises or []),
            }
        else:
            return {"error": f"Unknown workout_type '{workout_type}'. Use 'cycling', 'running', or 'strength'."}
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
# Tool: logout_coros
# ---------------------------------------------------------------------------

@mcp.tool()
async def logout_coros() -> dict:
    """Logout from the Coros Training Hub.

    Invalidates the current session token on the server.
    After calling this, you must re-authenticate.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated."}
    try:
        return await _run_with_auth(coros_api.logout, auth)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: update_account
# ---------------------------------------------------------------------------

@mcp.tool()
async def update_account(nickname: str = "", stature: int = 0, weight: float = 0.0) -> dict:
    """Update Coros account profile fields.

    Parameters
    ----------
    nickname : str
        New display name.
    stature : int
        Height in centimeters.
    weight : float
        Weight in kilograms.

    Returns
    -------
    dict with updated profile data.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    updates = {}
    if nickname:
        updates["nickname"] = nickname
    if stature:
        updates["stature"] = stature
    if weight:
        updates["weight"] = weight
    if not updates:
        return {"error": "No fields to update. Provide nickname, stature, or weight."}
    try:
        return await _run_with_auth(coros_api.update_account, auth, updates)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_training_library
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_training_library(
    region: str = "cn",
    locale: str = "zh-CN",
    sport_type: str | None = None,
    difficulty: str | None = None,
    category: str | None = None,
) -> dict:
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
    sport_type : str or None
        Filter by sport type.  e.g. "run", "cycling", "strength".
        None (default) returns all sport types.
    difficulty : str or None
        Filter by difficulty level.  e.g. "beginner", "intermediate", "advanced".
        None (default) returns all levels.
    category : str or None
        Filter by category.  "workout" for single workouts, "plan" for
        multi-week training plans.  None (default) returns both.

    Returns
    -------
    dict with keys: programs (list of TrainingProgram), count, region, locale
    """
    try:
        programs = await coros_api.fetch_training_library(
            region, locale, sport_type, difficulty, category,
        )
        return {
            "programs": [p.model_dump() for p in programs],
            "count": len(programs),
            "region": region,
            "locale": locale,
        }
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: import_training_program
# ---------------------------------------------------------------------------

@mcp.tool()
async def import_training_program(linked_id: str, category: str = "workout", region_id: int = 1, name: str | None = None) -> dict:
    """Import a public training program from the COROS library into your account.

    This copies a workout or training plan from the official COROS training
    library into your personal workout library, where it can be synced to
    your watch and scheduled on your training calendar.

    Use get_training_library first to browse available programs.  Each
    program in the catalog has a linked_id — pass that as the linked_id
    parameter here.

    Parameters
    ----------
    linked_id : str
        Training Hub program ID.  Use the linked_id field from
        get_training_library results, NOT program_id (the MongoDB _id).
        For example: "476133458610143331"
    category : str
        "workout" for single workouts, "plan" for multi-week training plans.
        Default: "workout".
    region_id : int
        Region mapping: 1 = China, 2 = US, 3 = EU.  Default: 1.
    name : str or None
        Custom display name for the imported program.  Pass the title from
        get_training_library results to get a human-readable name like
        "20min全力骑行" instead of the internal code "W30281".
        Default: None (API assigns automatic internal code).

    Returns
    -------
    dict with keys: imported_id, name, category, total_exercises,
    estimated_time_s

    Notes
    -----
    After importing, use list_workouts to find the new program by its
    imported_id, and schedule_workout to add it to your calendar.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    if category not in ("workout", "plan"):
        return {"error": f"category must be 'workout' or 'plan', got '{category}'"}

    try:
        result = await _run_with_auth(
            coros_api.import_training_program,
            auth, linked_id, category, region_id, name,
        )
        return result
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: estimate_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def estimate_workout(workout_id: str = "", workout_data: dict | None = None) -> dict:
    """Estimate training metrics for a workout — by saved ID or raw JSON.

    Calls /training/program/calculate with the full workout structure
    to return estimated duration, distance, training load, and an
    exercise bar chart for visualization.

    Parameters
    ----------
    workout_id : str
        Saved workout program ID (from manage_workout action="list").
    workout_data : dict, optional
        Raw workout JSON with exercises array. Use this to preview a
        workout before saving it.

    At least one of workout_id or workout_data must be provided.

    Returns
    -------
    dict with keys: planDuration, planDistance, planTrainingLoad,
    planSets, exerciseBarChart, etc.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    try:
        if workout_id and not workout_data:
            workout_data = await coros_api._fetch_raw_workout(auth, workout_id)
            if workout_data is None:
                return {"error": f"Workout not found: {workout_id}"}
        if not workout_data:
            return {"error": "Provide workout_id or workout_data."}
        return await _run_with_auth(coros_api.fetch_program_calculate, auth, workout_data)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_dashboard_detail
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_dashboard_detail() -> dict:
    """Fetch enriched Coros dashboard with 7-day details and planned targets.

    GET /dashboard/detail/query — returns richer data than get_dashboard,
    including upcoming scheduled workouts (targetList), daily metrics
    (detailList), recent sport activities (sportDataList), and training
    summary (summaryInfo: ATI, CTI, tiredRate, trainingLoadRatio).

    Returns
    -------
    dict with keys:
    - summaryInfo: training status summary
    - detailList: 7 days of daily metrics (ATI, CTI, stamina, tiredRate)
    - sportDataList: recent sport activity summaries
    - targetList: upcoming scheduled workouts for next 7 days
    - currentWeekRecord / record: distance/duration/tl records
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    try:
        return await _run_with_auth(coros_api.fetch_dashboard_detail, auth)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_team_dashboard
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_team_dashboard() -> dict:
    """Fetch team dashboard with performance scores and training zones.

    GET /dashboard/team/query — returns performance scores and zone tables
    that aren't available in the personal dashboard. Includes:

    - Performance scores (0-100): aerobicEnduranceScore,
      anaerobicCapacityScore, anaerobicEnduranceScore,
      lactateThresholdCapacityScore
    - LTHR and lthrZone: lactate threshold heart rate with 6-zone breakdown
    - LTSP and ltspZone: lactate threshold pace with pace zone breakdown
    - fitnessMaxHr, cycleLevelHr, fullRecoveryHours
    - sportDataSummary: total activity count

    Returns
    -------
    dict with keys: summaryInfo (scores + zones), sportDataSummary.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    try:
        return await _run_with_auth(coros_api.fetch_team_dashboard, auth)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Tool: get_team_info
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_team_info(team_id: str = "") -> dict:
    """Fetch single team detail (GET /team/info).

    Parameters
    ----------
    team_id : str
        Team ID (default: auto-detect primary team).

    Returns
    -------
    dict with team details (name, members, creator, etc.).
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _run_with_auth(coros_api.fetch_team_info, auth, team_id)
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Coach analysis helpers
# ---------------------------------------------------------------------------

async def _safe_fetch(fn, fallback=None):
    """Call fn() and return fallback on any exception."""
    try:
        return await fn()
    except Exception:
        return fallback


async def _fetch_daily_status_data(weeks: int = 2) -> dict:
    """Fetch 5 APIs needed for daily status: training_analysis, sleep, daily_health, dashboard, profile.

    Each data source is independently fetched with fallback.
    """
    from datetime import datetime, timedelta

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=max(weeks, 1))
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    auth = await _get_auth()

    analysis = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_training_analysis, auth, start_day, end_day),
        {},
    )
    daily_records = analysis.get("daily_records", []) if isinstance(analysis, dict) else []

    sleep_raw = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_sleep, auth, start_day, end_day),
        [],
    )
    sleep_records = [
        r.model_dump() if hasattr(r, "model_dump") else r for r in (sleep_raw or [])
    ]

    health_raw = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_daily_health, auth, start_day, end_day),
        [],
    )
    health_records = [
        r.model_dump() if hasattr(r, "model_dump") else r for r in (health_raw or [])
    ]

    dashboard = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_dashboard, auth), {},
    )

    profile = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_user_profile, auth), {},
    )

    return {
        "daily_records": daily_records,
        "sleep_records": sleep_records,
        "health_records": health_records,
        "dashboard": dashboard or {},
        "profile": profile or {},
    }


async def _fetch_weekly_report_data(weeks: int = 4) -> dict:
    """Fetch 3 APIs needed for weekly report: training_analysis, sleep, activities.

    Each data source is independently fetched with fallback.
    """
    from datetime import datetime, timedelta

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=max(weeks, 1))
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    auth = await _get_auth()

    analysis = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_training_analysis, auth, start_day, end_day),
        {},
    )
    daily_records = analysis.get("daily_records", []) if isinstance(analysis, dict) else []

    sleep_raw = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_sleep, auth, start_day, end_day),
        [],
    )
    sleep_records = [
        r.model_dump() if hasattr(r, "model_dump") else r for r in (sleep_raw or [])
    ]

    activities_raw, _ = await _safe_fetch(
        lambda: _run_with_auth(coros_api.fetch_activities, auth, start_day, end_day, size=50),
        ([], 0),
    )
    activities = [
        a.model_dump() if hasattr(a, "model_dump") else a for a in (activities_raw or [])
    ]

    return {
        "daily_records": daily_records,
        "sleep_records": sleep_records,
        "activities": activities,
    }
# ---------------------------------------------------------------------------
# Scene tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_daily_status(weeks: int = 2) -> dict:
    """Fetch daily health and training data from Coros.

    Returns raw data from 5 endpoints: training_analysis, sleep, daily_health,
    dashboard, user_profile. Use when you need a snapshot of current state.

    Parameters
    ----------
    weeks : int
        Number of weeks of data (default 2, max 12).

    Returns
    -------
    dict with: daily_records, sleep_records, health_records, dashboard, profile
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _fetch_daily_status_data(weeks=min(weeks, 12))
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def get_weekly_report(weeks: int = 4) -> dict:
    """Fetch weekly training data from Coros.

    Returns raw data from 3 endpoints: training_analysis, sleep, activities.
    Use when you need a multi-week view of training volume and sleep.

    Parameters
    ----------
    weeks : int
        Number of weeks of data (default 4, max 24).

    Returns
    -------
    dict with: daily_records, sleep_records, activities
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _fetch_weekly_report_data(weeks=min(weeks, 24))
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def analyze_workout(activity_id: str, sport_type: int = 0) -> dict:
    """Get full detail for a single completed workout with all metrics.

    Parameters
    ----------
    activity_id : str
        The activity ID (labelId) from list_activities.
    sport_type : int
        Sport type ID (e.g., 100=Running, 200=Road Bike). Default 0.

    Returns
    -------
    dict with full activity detail including lap data, heart rate zones, pace, and power.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        detail = await _run_with_auth(
            coros_api.fetch_activity_detail, auth, activity_id, sport_type,
        )
        if hasattr(detail, "model_dump"):
            return detail.model_dump()
        return detail
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def check_plan(start_day: str, end_day: str) -> dict:
    """Fetch scheduled training plan summary from Coros.

    Returns projected ATI, CTI, and training load ratio per week.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.

    Returns
    -------
    dict with raw schedule summary data (weeks, projections, load curves)
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        raw = await _run_with_auth(coros_api.fetch_schedule_summary, auth, start_day, end_day)
        if hasattr(raw, "model_dump"):
            return raw.model_dump()
        return raw
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def manage_plan(
    action: str,
    plan_data: dict | None = None,
    plan_id: str = "",
) -> dict:
    """Unified training plan management — list, create, update, or delete.

    Parameters
    ----------
    action : str
        "list" — return all training plans
        "create" — create a new plan (requires plan_data)
        "update" — update an existing plan (requires plan_data with id)
        "delete" — delete a plan by plan_id
    plan_data : dict, optional
        Full plan JSON (required for create/update).
    plan_id : str, optional
        Plan ID (required for delete).

    Returns
    -------
    dict with plan data, list, or confirmation.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    valid_actions = {"list", "create", "update", "delete"}
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Use one of: {', '.join(sorted(valid_actions))}."}

    try:
        if action == "list":
            items = await _run_with_auth(coros_api.fetch_plans, auth)
            return {"plans": items or [], "count": len(items or [])}
        elif action == "create":
            if plan_data is None:
                return {"error": "plan_data is required for create action."}
            return await _run_with_auth(coros_api.create_plan, auth, plan_data)
        elif action == "update":
            if plan_data is None:
                return {"error": "plan_data is required for update action."}
            return await _run_with_auth(coros_api.update_plan, auth, plan_data)
        elif action == "delete":
            if not plan_id:
                return {"error": "plan_id is required for delete action."}
            await _run_with_auth(coros_api.delete_plan, auth, plan_id)
            return {"deleted": True, "plan_id": plan_id, "message": "Plan deleted."}
    except Exception as exc:
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
