from typing import Optional
from pydantic import BaseModel


class SleepPhases(BaseModel):
    deep_minutes: Optional[int] = None
    light_minutes: Optional[int] = None
    rem_minutes: Optional[int] = None
    awake_minutes: Optional[int] = None
    nap_minutes: Optional[int] = None    # shortSleepTime — daytime naps


class SleepRecord(BaseModel):
    date: str
    total_duration_minutes: Optional[int] = None
    phases: Optional[SleepPhases] = None
    avg_hr: Optional[int] = None
    min_hr: Optional[int] = None
    max_hr: Optional[int] = None
    quality_score: Optional[int] = None  # -1 = not computed


class HRVRecord(BaseModel):
    date: str
    avg_sleep_hrv: Optional[float] = None    # Nacht-Durchschnitt RMSSD (ms)
    baseline: Optional[float] = None          # sleepHrvBase — rolling baseline
    standard_deviation: Optional[float] = None  # sleepHrvSd
    interval_list: Optional[list[int]] = None   # sleepHrvIntervalList — percentile bands


class StressRecord(BaseModel):
    date: str
    avg_stress: Optional[int] = None              # average daily stress level
    avg_stress_ordinary: Optional[int] = None      # ordinary daily stress
    stress_duration_seconds: Optional[int] = None  # total time under stress
    stress_duration_ordinary_seconds: Optional[int] = None


class DailyHealthRecord(BaseModel):
    """Combined daily health stats from the Coros mobile API — data not available
    via the Training Hub web API."""
    date: str
    # Activity
    steps: Optional[int] = None
    calories: Optional[int] = None
    # Stress
    stress: Optional[StressRecord] = None
    # Sleep (embedded — same structure as SleepRecord.phases)
    sleep_deep_minutes: Optional[int] = None
    sleep_light_minutes: Optional[int] = None
    sleep_rem_minutes: Optional[int] = None
    sleep_awake_minutes: Optional[int] = None
    sleep_nap_minutes: Optional[int] = None
    sleep_total_minutes: Optional[int] = None
    sleep_avg_hr: Optional[int] = None
    sleep_quality: Optional[int] = None


class DailyRecord(BaseModel):
    # Core identifiers
    date: str
    timestamp: Optional[int] = None                # Unix timestamp

    # HRV & Sleep
    avg_sleep_hrv: Optional[float] = None          # nightly average RMSSD (ms)
    baseline: Optional[float] = None               # sleepHrvBase — rolling baseline
    interval_list: Optional[list[int]] = None      # sleepHrvIntervalList

    # Heart rate
    rhr: Optional[int] = None                      # resting heart rate (bpm)
    test_rhr: Optional[int] = None                 # test resting HR (bpm)
    lthr: Optional[int] = None                     # lactate threshold HR (bpm)

    # Training load
    training_load: Optional[int] = None            # daily training load
    training_load_target: Optional[float] = None   # target training load
    training_load_ratio: Optional[float] = None    # acute/chronic ratio
    training_load_ratio_state: Optional[int] = None  # 1=low, 2=optimal, 3=high
    training_load_ratio_zone_list: Optional[list[dict]] = None  # zone boundaries
    t7d: Optional[int] = None                      # 7-day training load
    t28d: Optional[int] = None                     # 28-day training load
    ct7d_max_fixed: Optional[float] = None         # 7-day chronic TL max
    ct7d_min: Optional[float] = None               # 7-day chronic TL min
    recomend_tl_max: Optional[float] = None        # recommended TL upper bound
    recomend_tl_min: Optional[float] = None        # recommended TL lower bound

    # Fatigue & recovery
    tired_rate: Optional[float] = None             # fatigue rate (new model)
    tired_rate_old: Optional[float] = None         # fatigue rate (old model)
    tired_rate_state_new: Optional[int] = None     # fatigue state enum
    tired_rate_new_zone_list: Optional[list[dict]] = None  # fatigue zone boundaries
    tib: Optional[float] = None                    # training impact baseline

    # Performance indices
    ati: Optional[float] = None                    # acute training index
    cti: Optional[float] = None                    # chronic training index
    performance: Optional[int] = None              # performance index (-1 = no data)

    # Volume
    distance: Optional[float] = None               # daily distance (m)
    distance_target: Optional[float] = None        # target distance (m)
    duration: Optional[int] = None                 # daily duration (s)
    duration_target: Optional[int] = None          # target duration (s)

    # VO2max & stamina
    vo2max: Optional[int] = None
    stamina_level: Optional[float] = None          # base fitness
    stamina_level_7d: Optional[float] = None       # 7-day fitness trend

    # Pace
    ltsp: Optional[int] = None                     # lactate threshold pace (s/km)


class ActivitySummary(BaseModel):
    activity_id: str
    name: Optional[str] = None
    sport_type: Optional[int] = None
    sport_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[int] = None
    distance_meters: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    calories: Optional[int] = None
    training_load: Optional[int] = None
    avg_power: Optional[int] = None
    normalized_power: Optional[int] = None
    elevation_gain: Optional[int] = None


class TrainingProgram(BaseModel):
    """Public training program from the COROS training library (cn.coros.com/training)."""
    program_id: str                              # MongoDB _id from public catalog
    linked_id: Optional[str] = None              # Training Hub program ID (for import)
    title: str                                   # localized display name
    description: Optional[str] = None            # localized description (content field)
    category: str                                # "workout" or "plan"
    sport_types: list[str] = []                  # e.g. ["run", "cycling"]
    targets: list[str] = []                      # workout_target or plan_target
    difficulties: list[str] = []                 # e.g. ["beginner", "intermediate"]
    author: Optional[str] = None                 # "coros" for official
    author_name: Optional[str] = None            # localized author name
    download_count: int = 0
    icon_type: int = 1
    region: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class StoredAuth(BaseModel):
    access_token: str
    user_id: str
    region: str
    timestamp: int  # Unix milliseconds
    mobile_access_token: Optional[str] = None   # token for apieu.coros.com (sleep data)
    mobile_login_payload: Optional[dict] = None  # encrypted login body for auto-refresh
