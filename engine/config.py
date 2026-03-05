"""
config.py
---------
Centralized configuration constants for the SILSILA cascade engine.
"""

# ── API & Data Constants ───────────────────────────────────────────────────────
OTHH = "OTHH"
OPENSKY_URL = "https://opensky-network.org/api/flights/arrival"
USE_OPENSKY_BY_DEFAULT = False

# ── Operational Constraints (Minutes) ──────────────────────────────────────────
MIN_TURNAROUND_MINUTES = 45          # Minimum ground time for aircraft
CREW_MIN_REST_MINUTES = 10 * 60      # 10 hours between duties
MIN_PAX_CONNECT_MIN = 45             # Minimum passenger connection time
MAX_CREW_CONNECT_MIN = 240           # Max realistic crew transfer window (inbound→outbound)

# ── Financial Benchmarks (USD) ─────────────────────────────────────────────────
# IATA / industry-standard delay cost benchmarks (USD per minute)
COST_PAX_PER_MIN      = 0.85         # Passenger inconvenience / EU261 exposure
COST_AIRCRAFT_PER_MIN = 160.0        # Ground handling + fuel burn + slot costs

# ── Recovery Cost Constants (USD) ──────────────────────────────────────────────
# SWAP heuristic
SPARE_AIRCRAFT_POOL      = 2         # Spares Qatar keeps on ground at DOH (conservative)
SWAP_POSITIONING_COST    = 8_000.0   # Flat: ground repositioning, crew callout, paperwork
SWAP_READINESS_MINUTES   = 35        # Minutes until spare is ready at gate

# CANCEL heuristic
CANCEL_REBOOKING_COST_PER_PAX = 320.0   # Avg rebooking + hotel voucher (IATA 2024 benchmark)
CANCEL_EU261_THRESHOLD_MIN    = 180     # EU261 compensation kicks in above 3h delay
CANCEL_EU261_COST_PER_PAX     = 600.0   # EU261 Article 7 — medium-haul standard rate (EUR≈USD)

# DELAY (compress) heuristic
COMPRESS_TURNAROUND_MINUTES = 38     # Absolute minimum Qatar can achieve under pressure
                                     # (below standard 45 min — requires ops approval)

# ── Monte Carlo Constants (Phase 3) ────────────────────────────────────────────
# Delay distribution parameters — lognormal, calibrated to EUROCONTROL 2024 data
# EUROCONTROL: mean delay 17.5 min/flight, 46% of minutes are reactionary
MC_SCENARIOS            = 500        # Number of Monte Carlo scenarios
MC_DELAY_MU_LOG         = 2.85       # lognormal μ  → median initial delay ~17 min
MC_DELAY_SIGMA_LOG       = 0.95       # lognormal σ  → fat right tail (extreme events)
MC_DELAY_MIN_MIN        = 5.0        # Minimum sampled delay (minutes)
MC_DELAY_MAX_MIN        = 300.0      # Cap at 5 hours (beyond = diversion/cancel)
MC_RANDOM_SEED          = 42         # Reproducible runs
MC_HIGH_RISK_THRESHOLD  = 0.35       # Flight is "high risk" if cascade probability > 35%
MC_CRITICAL_COST_USD    = 50_000     # Scenario is "critical" if cascade cost > $50k
