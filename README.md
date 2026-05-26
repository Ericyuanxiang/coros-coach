# coros-ai-coach — 高驰AI教练

[中文文档](README_zh.md)

An MCP server that lets AI assistants access your complete Coros Training Hub data, create structured workouts, and manage your training calendar — all through natural language.

No API key. No official API. Your credentials stay local, encrypted in your system keyring. The server talks directly to Coros using the same endpoints the web app and mobile app use.

## About

**coros-ai-coach（高驰AI教练）** is an MCP (Model Context Protocol) server that bridges AI assistants with the COROS Training Hub ecosystem. It wraps the unofficial COROS API — the same endpoints used by the COROS web app and mobile app — into 25 MCP tools that any AI assistant can call.

Most COROS MCP servers stop at basic data retrieval (sleep, HRV, activities). coros-ai-coach goes several steps further:

- **Training plan library** — Browse and import 200+ official COROS programs from coaches and elite athletes. Filter by sport, difficulty, and category across three regions (CN/US/EU) with full i18n support.
- **Workout builder** — Create running workouts with 3 heart rate zone models (MaxHR, %HRR, %LTHR), pace targets, power, cadence, and equivalent pace. Cycling workouts with wattage zones. Strength circuits from the COROS exercise catalogue. All with interval/repeat support.
- **Calendar management** — Full CRUD on your training calendar: view, schedule, reschedule, remove. Plus aggregated volume summaries.
- **Daily health** — Steps, calories, stress levels from the mobile API — data not available through the Training Hub web API.

The server authenticates with your COROS credentials (MD5-hashed for web, AES-128-CBC encrypted for mobile — key reverse-engineered from the COROS Android APK). Tokens are stored in your system keyring and auto-refresh transparently. No data ever leaves your machine except to COROS servers.

## What you can do

Ask your assistant questions in plain English (or any language):

- *"How was my sleep this week? Break it down by deep, REM, and light."*
- *"What's my 4-week HRV trend? Am I above or below baseline?"*
- *"Find me a beginner 10K training plan from the Coros library and import it."*
- *"Create a 60-minute zone 2 run with a 10-minute warmup and 5-minute cooldown."*
- *"Schedule that workout for Thursday and move my existing Thursday session to Friday."*
- *"Show me my training load ratio over the last month — am I overtraining?"*
- *"Build a core strength circuit: plank, crunches, leg raises, 3 sets."*
- *"What's my lactate threshold heart rate and pace right now?"*
- *"How's my training lately? Am I ready to race?"*
- *"Should I train hard today or take it easy?"*

## How it's different

This is a fork of [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp) that adds a significant layer of capabilities on top. The original covers basic sleep and activity retrieval. coros-ai-coach adds:

| Domain | Original | coros-ai-coach |
|--------|----------|-------------|
| Daily health | — | Steps, calories, stress levels (mobile API) |
| Training library | — | Browse 200+ official programs, import with one click |
| Running workouts | — | Full HR zone builder — 3 zone models (MaxHR, %HRR, %LTHR), pace, power, cadence |
| Strength workouts | — | Circuit builder from Coros exercise catalogue |
| Calendar | List only | View, schedule, reschedule, remove, volume summary |
| Dashboard | — | Quick "how am I today?" snapshot |
| User profile | — | HR zones, pace zones, power zones, physiological baselines |
| Workout management | Create/list | Create, list, delete workouts AND plans |
| Library browsing | — | Filter by sport, difficulty, category, region, language |

## Tools

### Health & readiness

| Tool | What it returns |
|------|----------------|
| `get_dashboard` | Current HRV, sleep quality, readiness score, recent activity summaries, fitness trend. No date params — always returns the latest ~7 days. |
| `get_daily_health` | Steps, calories, stress level (average + duration), and sleep stage breakdown for each day. From the mobile API — data not available through Training Hub. |
| `get_sleep_data` | Per-night sleep stages (deep, light, REM, awake), naps, sleep heart rate (avg/min/max), and quality score. Configurable 1–52 weeks. |
| `get_user_profile` | All physiological baselines: max HR, resting HR, lactate threshold HR, lactate threshold pace, FTP. HR zones for 3 models, pace zones, cycling power zones. |

### Training analysis

| Tool | What it returns |
|------|----------------|
| `get_training_analysis` | The full Coros "数据分析" report. 35 daily metrics: HRV (RMSSD + baseline), resting HR, training load (daily/acute/chronic), fatigue rate, VO2max, stamina, performance index. Weekly summaries with recommended load ranges. Sport-by-sport breakdown. Intensity distribution. Personal records. Configurable 1–24 weeks. |

### Activities

| Tool | What it returns |
|------|----------------|
| `list_activities` | Paginated activity list: sport type, duration, distance, HR, power, calories, training load, elevation. |
| `get_activity_detail` | Full activity detail: lap data, HR zones, power zones, all sport-specific metrics. |
| `list_sport_types` | All Coros sport type IDs and names — useful reference for creating workouts. |

### Workout builder

| Tool | What it returns |
|------|----------------|
| `create_run_workout` | Running workout with HR zone targets (zone 1–6). Three zone models: MaxHR, %HRR (heart rate reserve), %LTHR (lactate threshold). Also supports pace targets (sec/km), power (watts), cadence (spm), and equivalent pace. Supports intervals via repeat groups. |
| `create_workout` | Cycling workout with power targets (watts). Default indoor cycling, supports road bike. Interval/repeat support. |
| `create_strength_workout` | Strength circuit program. Exercises pulled from the Coros catalogue (use `list_exercises` to browse). Configurable sets, reps or timed targets, rest periods. |
| `list_exercises` | The Coros exercise catalogue for strength/conditioning. Each exercise has an `origin_id`, T-code name, and `sid_` overview key. |

### Training library

| Tool | What it returns |
|------|----------------|
| `get_training_library` | Browse the public COROS training library: 200+ programs created by COROS coaches and athletes. Each entry has a title, description, sport types, difficulty level, training targets, author, and download count. Filter by sport_type, difficulty, category. Choose region (cn/us/eu) and language (zh-CN, en-US, de, etc.). |
| `import_training_program` | Import a library program into your personal account with one click. Auto-resolves internal codes to human-readable names. Works for both single workouts and multi-week training plans. |

### Calendar

| Tool | What it returns |
|------|----------------|
| `list_planned_activities` | Everything scheduled on your training calendar for a date range. |
| `schedule_workout` | Put a workout from your library onto a specific calendar day. |
| `remove_scheduled_workout` | Remove a scheduled session from the calendar. |
| `get_training_summary` | Aggregated volume totals (duration, load, session count) over a date range. Lighter than listing all activities. |

### Workout & plan management

| Tool | What it returns |
|------|----------------|
| `list_workouts` | All saved workout programs and training plans in your account. Includes structure preview: steps, durations, intensity targets. |
| `delete_workout` | Remove a workout program. |
| `delete_plan` | Remove a training plan. |

### Coach briefing

| Tool | What it returns |
|------|----------------|
| `get_coach_briefing` | Intelligent coaching briefing. One call, no manual orchestration. Internally fetches 6 data sources in parallel and runs 10 professional analysis functions based on TrainingPeaks PMC, Coros EvoLab, and 2025 endurance coaching consensus. Returns readiness score (0-5), fatigue level, training status, HRV trend, sleep analysis, today's training recommendation with intensity/duration/evidence, weekly load comparison, fitness trends, and alerts (HRV decline, sleep debt, overtraining risk, inactivity). Just ask "How's my training lately?" |

### Auth

| Tool | What it returns |
|------|----------------|
| `authenticate_coros` | Log in with email + password. Stores both web and mobile tokens. |
| `authenticate_coros_mobile` | Mobile-only login (sleep + daily health data). |
| `check_coros_auth` | Token validity status, expiry time, mobile token state. |

## Architecture

### Dual API

Coros splits data across two separate API systems:

| | Training Hub (web) | Mobile API |
|---|---|---|
| **Host** | `teameuapi.coros.com` (EU) / `teamapi.coros.com` (US) | `apieu.coros.com` (EU) / `api.coros.com` (US) |
| **Auth** | MD5-hashed password → `accessToken` header | AES-128-CBC encrypted credentials (key reverse-engineered from Coros APK) |
| **Token TTL** | ~24 hours | ~1 hour |
| **Refresh** | Re-authenticate with stored credentials | Replay stored encrypted login payload |
| **Data** | HRV, training metrics, activities, workouts, calendar | Sleep stages, steps, calories, stress |

`get_training_analysis` goes further: it calls two Training Hub endpoints in parallel (`/analyse/dayDetail/query` for configurable date range + `/analyse/query` for VO2max/fitness fields) and merges them into a single result.

### Token storage

Priority chain on read: `COROS_ACCESS_TOKEN` env var → system keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service) → AES-256-GCM encrypted local file.

On write, both keyring and encrypted file are updated. The entire `StoredAuth` object — web token, mobile token, and mobile login payload for replay — is serialized as JSON into a single credential.

### Auto-auth

If `COROS_EMAIL` and `COROS_PASSWORD` are set (via `.env` or environment), the server authenticates automatically on the first request and re-authenticates transparently when the token expires or is rejected. No manual auth command needed.

## Setup

### 1. Install

```bash
git clone https://github.com/Ericyuanxiang/coros-ai-coach.git
cd coros-ai-coach
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Configure

Create `.env` in the project directory:

```env
COROS_EMAIL=you@example.com
COROS_PASSWORD=yourpassword
COROS_REGION=eu
```

Valid regions: `eu`, `us`, `cn`. The server auto-authenticates on first use.

### 3. Verify

```bash
coros-ai-coach test
```

Checks Python version, dependencies, authentication, and API connectivity in one step.

### 4. Register with Claude Code

```bash
claude mcp add coros -- /path/to/coros-ai-coach/.venv/bin/coros-ai-coach serve
```

Or in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "coros": {
      "command": "/path/to/coros-ai-coach/.venv/bin/coros-ai-coach",
      "args": ["serve"]
    }
  }
}
```

### Manual auth (optional)

If you prefer not to use `.env`:

```bash
coros-ai-coach auth          # Prompted login — stores web + mobile tokens
coros-ai-coach auth-status   # Check expiry and token state
coros-ai-coach auth-clear    # Remove all stored tokens
```

## Requirements

- Python >= 3.11
- A Coros account (any region: EU, US, Asia/China)

## Dependencies

- [fastmcp](https://github.com/jlowin/fastmcp) — MCP server framework
- [httpx](https://www.python-httpx.org/) — async HTTP client
- [pycryptodome](https://pycryptodome.readthedocs.io/) — AES encryption for mobile API auth
- [keyring](https://github.com/jaraco/keyring) — cross-platform credential storage
- [pydantic](https://docs.pydantic.dev/) — data validation and serialization
- [python-dotenv](https://github.com/theskumar/python-dotenv) — `.env` file support

## Structure

```
coros-ai-coach/
├── server.py           # FastMCP tool definitions (25 tools)
├── coros_api.py        # HTTP client, dual-API auth, AES encryption, response parsers
├── coach.py            # Coaching analysis engine (readiness, fatigue, training status, recommendations)
├── models.py           # Pydantic v2 data models
├── cli.py              # CLI entry point (serve, auth, test)
├── auth/               # Token storage: keyring + AES-256-GCM encrypted file fallback
└── pyproject.toml
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **"Not authenticated"** | Run `coros-ai-coach test` to verify your `.env` credentials. If `.env` is missing, run `coros-ai-coach auth` for interactive login. |
| **Auth fails / wrong region** | Check `COROS_REGION` in `.env`. Must be `eu`, `us`, or `cn`. EU tokens don't work on US/CN servers and vice versa. |
| **Mobile API not available (no sleep data)** | Mobile login may be blocked in some regions. Run `coros-ai-coach auth-mobile` to retry. Sleep data is provided on a best-effort basis. |
| **Token keeps expiring** | Web tokens last ~24h and refresh automatically. If you see frequent auth errors, check your system clock is accurate. |
| **Keyring errors on Linux** | Install `dbus-python` or `secretstorage`. If unavailable, the server falls back to an AES-256-GCM encrypted local file. |
| **Tools don't appear in Claude Code** | Restart Claude Code after registering the MCP server. Run `coros-ai-coach test` first to verify the server works standalone. |
| **ImportError on startup** | Run `pip install -e .` to reinstall dependencies. Check Python >= 3.11 with `python --version`. |

## Credits

Forked from [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp) (MIT License).
