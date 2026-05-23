# coros-coach

Your AI-powered Coros Training Hub companion. Ask your assistant about sleep quality, HRV trends, training load, or have it build workouts and import training plans — all through natural language.

**No API key needed.** Authenticates directly with your Coros account. Tokens stored in your system keyring, never sent anywhere but Coros.

## What makes this different

Most Coros MCP servers only surface basic sleep and activity data. coros-coach goes deeper:

| Capability | What you get |
|---|---|
| **Training library** | Browse 200+ official COROS workouts and plans, import with one command |
| **Daily health** | Steps, calories, stress levels, sleep stages — from the mobile API |
| **Workout builder** | Create running workouts with HR zone targets (MaxHR / %HRR / %LTHR), cycling workouts with power, strength circuits |
| **Training analysis** | 35 metrics per day: HRV, RHR, LTHR, training load, fatigue, VO2max, stamina, performance index |
| **Dashboard** | Quick snapshot: current HRV, sleep quality, readiness, recent activities |
| **Calendar** | View and manage your training schedule — schedule, reschedule, remove |

## Quick start

### 1. Install

```bash
git clone https://github.com/Ericyuanxiang/coros-coach.git
cd coros-coach
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Configure

Create a `.env` file in the project directory:

```
COROS_EMAIL=you@example.com
COROS_PASSWORD=yourpassword
COROS_REGION=eu
```

Auto-authenticates on first request. No manual auth step.

### 3. Add to Claude Code

```bash
claude mcp add coros -- /path/to/coros-coach/.venv/bin/coros-coach serve
```

Or Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "coros": {
      "command": "/path/to/coros-coach/.venv/bin/coros-coach",
      "args": ["serve"]
    }
  }
}
```

### Manual auth (alternative)

```bash
coros-coach auth          # Full auth (web + mobile tokens)
coros-coach auth-web      # Web API only
coros-coach auth-status   # Check token status
coros-coach auth-clear    # Remove stored tokens
```

## Example questions

- "How was my sleep this week — deep vs REM breakdown?"
- "What's my HRV trend over the last month?"
- "Show me my training load, fatigue, and performance for the last 2 weeks"
- "Search the Coros training library for beginner 5K plans"
- "Import that 8-week half marathon plan into my account"
- "Create a 60-minute zone 2 run with a 10-minute warmup"
- "Build a 3-set strength circuit: squats, lunges, planks"
- "What's on my training calendar next week?"

## Tools

| Tool | Description |
|------|-------------|
| `authenticate_coros` | Log in with email + password |
| `check_coros_auth` | Check token validity |
| `get_dashboard` | Quick athlete snapshot |
| `get_training_analysis` | Full analysis: daily metrics, weekly summaries, sport stats (1–24 weeks) |
| `get_training_summary` | Calendar volume overview (totals without full detail) |
| `get_sleep_data` | Nightly sleep stages and sleep HR |
| `get_daily_health` | Steps, calories, stress, sleep (mobile API) |
| `list_activities` | Activities for a date range |
| `get_activity_detail` | Full activity detail (laps, zones) |
| `list_workouts` | Your saved workout programs |
| `create_run_workout` | Running workout with HR zone or pace targets |
| `create_workout` | Cycling workout with power targets |
| `create_strength_workout` | Strength circuit with sets/reps |
| `delete_workout` | Remove a workout program |
| `delete_plan` | Remove a training plan |
| `list_planned_activities` | Training calendar view |
| `schedule_workout` | Add workout to calendar |
| `remove_scheduled_workout` | Remove from calendar |
| `get_training_library` | Browse official COROS training programs |
| `import_training_program` | Import a library program into your account |
| `list_sport_types` | All supported sport type IDs |
| `list_exercises` | Strength exercise catalogue |
| `get_user_profile` | HR/pace/power zone tables |

## Requirements

- Python >= 3.11
- A Coros account

## Project structure

```
coros-coach/
├── server.py           # MCP tool definitions
├── coros_api.py        # HTTP client, auth, parsers
├── models.py           # Pydantic data models
├── cli.py              # CLI entry point
├── auth/               # Token storage (keyring + encrypted fallback)
└── pyproject.toml
```

## Credits

Forked from [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp) (MIT License). Extended with training library import, daily health data, run/strength workout builders, training calendar management, and dashboard support.
