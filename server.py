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
import time
import json

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

import coros_api
from coros_api import TOKEN_TTL_MS

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

mcp = FastMCP("coros-ai-coach")

_auth_cache: tuple[float, object] | None = None  # (expires_at, auth_obj)


async def _get_auth():
    """Return StoredAuth, auto-refreshing if token expired."""
    global _auth_cache
    now = time.time() * 1000

    if _auth_cache and _auth_cache[0] > now:
        return _auth_cache[1]

    auth = coros_api.get_stored_auth()
    if auth is None:
        auth = await coros_api.try_auto_login()

    if auth:
        _auth_cache = (now + TOKEN_TTL_MS - 60000, auth)
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
        return _tool_error(exc)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
