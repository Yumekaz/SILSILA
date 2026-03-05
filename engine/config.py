"""
config.py
---------
Centralized configuration constants for the SILSILA cascade engine.
"""

# ── API & Data Constants ───────────────────────────────────────────────────────
OTHH = "OTHH"
OPENSKY_URL = "https://opensky-network.org/api/flights/arrival"

# ── Operational Constraints (Minutes) ──────────────────────────────────────────
MIN_TURNAROUND_MINUTES = 45          # Minimum ground time for aircraft
CREW_MIN_REST_MINUTES = 10 * 60      # 10 hours between duties
MIN_PAX_CONNECT_MIN = 45             # Minimum passenger connection time

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
