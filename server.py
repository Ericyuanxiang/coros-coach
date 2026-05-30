"""
Coros AI Coach MCP Server

Usage:
    python server.py

MCP config:
    claude mcp add coros \\
      -e COROS_EMAIL=you@example.com \\
      -e COROS_PASSWORD=yourpass \\
      -e COROS_REGION=eu \\
      -- python /path/to/coros-ai-coach/server.py
"""

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

import coros_api

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

mcp = FastMCP("coros-ai-coach")


async def _get_auth():
    """Return StoredAuth. Retry with fresh login if cached token fails."""
    auth = coros_api.get_stored_auth()
    if auth is None:
        auth = await coros_api.try_auto_login()
    return auth


async def _run_with_auth(fn, auth, *args, **kwargs):
    return await fn(auth, *args, **kwargs)


def _tool_error(exc: Exception, **extra) -> dict:
    return {"error": str(exc), **extra}


# ---------------------------------------------------------------------------
# Auth tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def authenticate_coros(email: str, password: str, region: str = "eu") -> dict:
    """Authenticate with Coros Training Hub."""
    try:
        auth = await coros_api.login(email, password, region)
        return {"authenticated": True, "user_id": auth.user_id, "region": auth.region}
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def authenticate_coros_mobile(email: str, password: str, region: str = "eu") -> dict:
    """Authenticate with Coros mobile API (for sleep data)."""
    try:
        auth = await coros_api.login_mobile(email, password, region)
        return {"authenticated": True, "user_id": auth.user_id, "region": auth.region}
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def check_coros_auth() -> dict:
    """Check authentication status."""
    auth = await _get_auth()
    if auth is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user_id": auth.user_id,
        "region": auth.region,
        "has_mobile": bool(auth.mobile_access_token),
    }


# ---------------------------------------------------------------------------
# generate_plan — two-phase AI-embedded weekly plan builder
# ---------------------------------------------------------------------------

@mcp.tool()
async def generate_plan(start_day: str, phase: str = "base",
                         ai_decision: dict | None = None) -> dict:
    """Generate a weekly training plan — two-phase AI-embedded workflow.

    Phase 1 (ai_decision=None): returns state + catalog + rules for AI to
    fill in weekly_tl, daily_plan, and workout_picks.

    Phase 2 (ai_decision provided): validates AI's plan, imports selected
    courses, schedules them, and shows weekly projection.

    Parameters
    ----------
    start_day : str — Monday in YYYYMMDD format (e.g. "20260601")
    phase : str — "base" | "build" | "peak" | "taper"
    ai_decision : dict, optional
        {weekly_tl: int, daily_plan: list[7], workout_picks: dict}

    Returns Phase 1 framework or Phase 2 result.
    """
    from workflows.generate_plan import run
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated."}
    try:
        return await run(auth, start_day, phase, ai_decision)
    except Exception as exc:
        err = str(exc)
        if "token" in err.lower() or "access" in err.lower():
            # Token expired — force re-login and retry once
            auth = await coros_api.try_auto_login()
            if auth:
                try:
                    return await run(auth, start_day, phase, ai_decision)
                except Exception as exc2:
                    return _tool_error(exc2)
        return _tool_error(exc)


# ---------------------------------------------------------------------------
# Execution tools — AI uses these to act on generate_plan decisions
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_training_library(region: str = "cn", locale: str = "zh-CN",
                                sport_type: str | None = "run",
                                difficulty: str | None = None,
                                category: str = "workout") -> dict:
    """Browse the COROS public training library (65+ running workouts)."""
    try:
        programs = await coros_api.fetch_training_library(region, locale, sport_type, difficulty, category)
        return {"programs": [p.model_dump() for p in programs], "count": len(programs)}
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def create_workout(name: str, workout_type: str = "running",
                          sport_type: int = 100, steps: list[dict] | None = None,
                          description: str = "") -> dict:
    """Create a custom workout when catalog has no match."""
    auth = await _get_auth()
    if not auth: return {"error": "Not authenticated."}
    try:
        if workout_type == "running":
            if steps is None:
                steps = [{"name": description or name, "duration_minutes": 60,
                          "hr_low": 2, "hr_high": 3}]
            wid = await coros_api.create_run_workout(auth, name, steps)
        else:
            return {"error": f"Unsupported workout type: {workout_type}"}
        return {"created": True, "workout_id": wid, "name": name}
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def estimate_workout(workout_id: str) -> dict:
    """Calculate TL for a workout before scheduling."""
    auth = await _get_auth()
    if not auth: return {"error": "Not authenticated."}
    try:
        raw = await coros_api._fetch_raw_workout(auth, workout_id)
        if raw is None: return {"error": f"Workout not found: {workout_id}"}
        return await _run_with_auth(coros_api.fetch_program_calculate, auth, raw)
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def schedule_workout(workout_id: str, happen_day: str, sort_no: int = 1) -> dict:
    """Schedule a workout to the training calendar."""
    auth = await _get_auth()
    if not auth: return {"error": "Not authenticated."}
    try:
        await coros_api.schedule_workout(auth, workout_id, happen_day, sort_no)
        return {"scheduled": True, "workout_id": workout_id, "happen_day": happen_day}
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def get_weekly_projection(start_day: str, end_day: str) -> dict:
    """Get weekly training projection (same view as Coros app)."""
    auth = await _get_auth()
    if not auth: return {"error": "Not authenticated."}
    try:
        raw = await _run_with_auth(coros_api.fetch_schedule, auth, start_day, end_day)
        weeks = []
        if isinstance(raw, dict):
            for w in raw.get("weekStages", []):
                ws = w.get("trainSum", {})
                weeks.append({
                    "firstDayInWeek": w.get("firstDayInWeek"),
                    "long_term_load": ws.get("actualCti"),
                    "short_term_load": ws.get("actualAti"),
                    "load_ratio": round((ws.get("actualTrainingLoadRatio") or 0) * 100),
                    "plan_training_load": ws.get("planTrainingLoad"),
                    "plan_time": f"{ws.get('planDuration', 0) // 3600}h{(ws.get('planDuration', 0) % 3600) // 60}m",
                    "plan_distance_km": round(float(ws.get('planDistance', 0)) / 100000, 2),
                })
        return {"plan_name": raw.get("name") if isinstance(raw, dict) else None, "weeks": weeks}
    except Exception as exc:
        return _tool_error(exc)


@mcp.tool()
async def import_from_library(linked_id: str, category: str = "workout",
                               region_id: int = 1, name: str | None = None) -> dict:
    """Import a workout from the public training library."""
    auth = await _get_auth()
    if not auth: return {"error": "Not authenticated."}
    try:
        result = await coros_api.import_training_program(auth, linked_id, category, region_id, name)
        return {"imported": True, **result}
    except Exception as exc:
        return _tool_error(exc)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
