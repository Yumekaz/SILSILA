"""
config.py
---------
Centralized configuration constants for the SILSILA cascade engine.
"""

import os

from engine.cost_model import (
    CALIBRATED_AIRCRAFT_DELAY_COST_USD_PER_MIN,
    CALIBRATED_PASSENGER_DELAY_COST_USD_PER_MIN,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# -- API & Data Constants -------------------------------------------------------
OTHH = "OTHH"
OPENSKY_URL = "https://opensky-network.org/api/flights/arrival"
USE_OPENSKY_BY_DEFAULT = _env_bool("SILSILA_USE_OPENSKY_BY_DEFAULT", False)
OPENSKY_TIMEOUT_SECONDS = 10
OPENSKY_MAX_RETRIES = 2
OPENSKY_RETRY_BACKOFF_SECONDS = 1.25
OPENSKY_CIRCUIT_FAILURE_THRESHOLD = 3
OPENSKY_CIRCUIT_RESET_SECONDS = 300
DATA_FRESHNESS_WARN_SECONDS = 15 * 60
DATA_FRESHNESS_DEGRADE_SECONDS = 60 * 60

# -- Operational Constraints (Minutes) ------------------------------------------
MIN_TURNAROUND_MINUTES = 45
CREW_MIN_REST_MINUTES = 10 * 60
MIN_PAX_CONNECT_MIN = 45
MAX_CREW_CONNECT_MIN = 240

# -- Financial Benchmarks (USD) -------------------------------------------------
# Calibrated from EUROCONTROL Standard Inputs and ECB reference rates.
COST_PAX_PER_MIN = CALIBRATED_PASSENGER_DELAY_COST_USD_PER_MIN
COST_AIRCRAFT_PER_MIN = CALIBRATED_AIRCRAFT_DELAY_COST_USD_PER_MIN

# -- Recovery Cost Constants (USD) ----------------------------------------------
SPARE_AIRCRAFT_POOL = 2
SWAP_POSITIONING_COST = 8_000.0
SWAP_READINESS_MINUTES = 35

# Cancellation economics are calibrated dynamically in engine.cost_model.
CANCEL_DELAY_THRESHOLD_MIN = 180

# DELAY (compress) heuristic
COMPRESS_TURNAROUND_MINUTES = 38

# -- Monte Carlo Constants (Phase 3) --------------------------------------------
MC_SCENARIOS = 500
MC_DELAY_MU_LOG = 2.85
MC_DELAY_SIGMA_LOG = 0.95
MC_DELAY_MIN_MIN = 5.0
MC_DELAY_MAX_MIN = 300.0
MC_RANDOM_SEED = 42
MC_HIGH_RISK_THRESHOLD = 0.35
MC_CRITICAL_COST_USD = 50_000
