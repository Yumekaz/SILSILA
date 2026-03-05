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
# IATA delay cost benchmarks (USD per minute)
COST_PAX_PER_MIN = 0.85              # Passenger inconvenience / compensation
COST_AIRCRAFT_PER_MIN = 160.0        # Ground handling + fuel burn + slot costs
