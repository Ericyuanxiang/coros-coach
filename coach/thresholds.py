"""Training thresholds — tune these for individual athletes."""

# ---------------------------------------------------------------------------
# HRV
# ---------------------------------------------------------------------------
HRV_GOOD_THRESHOLD = -10     # deviation % from baseline — above this is Good
HRV_FAIR_THRESHOLD = -25     # below this is Poor; between = Fair
HRV_ALERT_THRESHOLD = -15    # consecutive days below this → alert
HRV_ALERT_STREAK = 3         # how many consecutive bad days trigger alert

# ---------------------------------------------------------------------------
# Sleep
# ---------------------------------------------------------------------------
SLEEP_OPTIMAL_MINUTES = 480  # 8 hours
SLEEP_GOOD_MINUTES = 420     # 7 hours → Good
SLEEP_FAIR_MINUTES = 360     # 6 hours → Fair
SLEEP_GOOD_QUALITY = 70
SLEEP_FAIR_QUALITY = 50
SLEEP_DEBT_ALERT_HOURS = 2   # debt > this over 3 nights → alert

# ---------------------------------------------------------------------------
# Resting HR
# ---------------------------------------------------------------------------
RHR_ELEVATED_BPM = 3         # bpm above 7d avg → point deduction
RHR_ELEVATED_ALERT_BPM = 5   # bpm above 7d avg → alert

# ---------------------------------------------------------------------------
# Fatigue (tired_rate numeric fallback zones)
# ---------------------------------------------------------------------------
FRESH_TIRED_RATE = -30
FATIGUED_TIRED_RATE = 0
OVERTRAINED_TIRED_RATE = 20

# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------
TREND_PCT = 5.0              # min % change to call a trend Rising or Falling
STAMINA_TREND_PCT = 2.0

# ---------------------------------------------------------------------------
# Inactivity
# ---------------------------------------------------------------------------
INACTIVITY_DAYS = 5          # days without training → alert

# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
DAYS_SINCE_TRAINING_RETURN = 14   # >2 weeks off → return-to-training protocol
SLEEP_DEBT_CAUTION = 2            # hours (3-night avg vs 8h target)
SLEEP_MIN_ATHLETE = 5             # hours — below this, injury risk 1.7x (Hatia 2024)
RHR_ELEVATED_CAUTION = 5          # bpm above 7d avg
RHR_ELEVATED_DAYS = 5             # consecutive days
HRV_LOW_DEVIATION = -25           # % — below baseline
HIGH_LOAD_DAYS = 3                # consecutive days with tl_ratio_state = 3
RETURN_VOLUME_FACTOR = 0.5        # 50% rule (Mujika & Padilla)
INTENSITY_RANK = {"Rest": 0, "Easy": 1, "Moderate": 2, "Hard": 3}

# ---------------------------------------------------------------------------
# Plan analysis
# ---------------------------------------------------------------------------
PLAN_LOAD_RATIO_SAFE = 0.8        # below this: safe zone
PLAN_LOAD_RATIO_EFFICIENT = 1.0   # 0.8-1.2: efficient training zone
PLAN_LOAD_RATIO_WARNING = 1.3     # 1.2-1.3: approaching limit
PLAN_LOAD_RATIO_DANGER = 1.5      # >1.5: injury risk RR 2.0-4.0 (Gabbett 2016)
PLAN_WEEKLY_LOAD_JUMP_PCT = 30    # >30% week-over-week load increase → warning
PLAN_CTI_FALLING_DAYS = 3         # consecutive days CTI falling → insufficient load
