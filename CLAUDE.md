# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`coros-coach` is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes Coros fitness data (sleep, HRV, training metrics, activities, workouts) to AI assistants. It uses the **unofficial** Coros API — no official API key required.

## Setup & Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Running the Server

```bash
# Run the MCP server directly:
python server.py

# Or register with Claude Code:
claude mcp add coros -- python /path/to/coros-coach/server.py
```

## CLI Commands

```bash
coros-coach auth           # Authenticate (web + mobile tokens)
coros-coach auth-web       # Web API only (no sleep data)
coros-coach auth-mobile    # Mobile API only (sleep data)
coros-coach auth-status    # Check token status
coros-coach auth-clear     # Remove stored tokens
```

## Architecture

The project wraps two separate Coros APIs behind a unified MCP interface:

### Dual API Design
- **Training Hub web API** (`teameuapi.coros.com` / `teamapi.coros.com`): HRV, daily metrics, activities, workouts. Auth via MD5-hashed password → `accessToken` header. Token TTL: 24 hours.
- **Mobile API** (`apieu.coros.com` / `apius.coros.com`): Sleep stage data (deep/light/REM/awake). Auth via AES-128-CBC encrypted credentials (key reverse-engineered from Coros APK). Token TTL: ~1 hour, **auto-refreshes** by replaying the stored encrypted login payload.

### Token Storage (`auth/`)
Priority chain for retrieval: `COROS_ACCESS_TOKEN` env var → system keyring → encrypted local file. On write, both keyring and encrypted file are updated (belt-and-suspenders). The entire `StoredAuth` object (web token + mobile token + mobile login payload for replay) is serialized as JSON and stored as a single credential.

### Key Files
- **`server.py`**: FastMCP tool definitions. Each `@mcp.tool()` function validates auth, delegates to `coros_api`, and returns a dict. This is the only file that imports from `fastmcp`.
- **`coros_api.py`**: All HTTP logic. Contains two sets of endpoints (Training Hub + mobile), the AES encryption for mobile auth, auto-refresh logic, and response parsers. The `fetch_training_analysis()` function merges two endpoints: `/analyse/dayDetail/query` (long range, no VO2max) + `/analyse/query` (last 84 days, has VO2max/fitness fields).
- **`models.py`**: Pydantic v2 models: `StoredAuth`, `DailyRecord`, `SleepRecord`/`SleepPhases`, `HRVRecord`, `ActivitySummary`.
- **`cli.py`**: CLI entry point registered as `coros-coach` script. Delegates to `coros_api.login()` / `login_mobile()`.

### API Response Pattern
All Coros API responses return `result: "0000"` on success. Any other value indicates an error — check `message` field. Large time-series fields (`graphList`, `frequencyList`, `gpsLightDuration`) are stripped from activity detail responses to keep them manageable.

### Region Handling
Regions (`eu`, `us`) map to different base URLs for both APIs. EU tokens only work on EU endpoints — mixing regions causes auth failures.
