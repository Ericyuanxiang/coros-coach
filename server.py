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
async def generate_plan(start_day: str = "",
                         phase: str = "base",
                         ai_decision: dict | None = None) -> dict:
    """Generate a weekly training plan. Two-phase: Phase 1 returns framework,
    Phase 2 (with ai_decision) executes the plan.

    start_day: next Monday's date, e.g. "20260601" or "2026-06-01"
    phase: ONLY "base", "build", "peak", or "taper". Default "base".
    ai_decision: omit in Phase 1. Required in Phase 2.
    """
    from workflows.generate_plan import run
    if phase not in ("base", "build", "peak", "taper"):
        return {"error": f"phase 必须是 base/build/peak/taper 之一, 不是 '{phase}'"}
    if not start_day:
        from datetime import date, timedelta
        today = date.today()
        days = (7 - today.weekday()) % 7 or 7
        start_day = (today + timedelta(days=days)).strftime("%Y%m%d")
    # Normalize date format: accept "2026-06-01", "2026/06/01", etc.
    start_day = start_day.replace("-", "").replace("/", "").replace(".", "")
    if len(start_day) != 8 or not start_day.isdigit():
        return {"error": f"日期格式需要 YYYYMMDD, 例如 '20260601'. 收到: '{start_day}'"}
    # Silently fix past dates (AI doesn't know it's 2026)
    from datetime import date, timedelta
    try:
        dt = date(int(start_day[:4]), int(start_day[4:6]), int(start_day[6:8]))
        today = date.today()
        if dt < today - timedelta(days=1):
            days = (7 - today.weekday()) % 7 or 7
            start_day = (today + timedelta(days=days)).strftime("%Y%m%d")
    except ValueError:
        return {"error": f"日期不存在: '{start_day}'"}
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




def main():
    mcp.run()


if __name__ == "__main__":
    main()
