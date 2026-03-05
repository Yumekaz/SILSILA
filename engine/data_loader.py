"""
data_loader.py
--------------
Loads a day's worth of Qatar Airways flights at Hamad International (DOH/OTHH).

Primary:   OpenSky Network REST API (free, real historical data)
Fallback:  Synthetic schedule built from real QR routes + realistic timing
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
from engine.config import (
    OTHH,
    OPENSKY_URL,
    MIN_TURNAROUND_MINUTES,
    CREW_MIN_REST_MINUTES
)

# Real Qatar Airways fleet sample (tail → aircraft type → seats)
QR_FLEET = {
    "A7-APA": {"type": "A380-800",    "seats": 517, "range_km": 15200},
    "A7-BAA": {"type": "B777-300ER",  "seats": 355, "range_km": 13650},
    "A7-BAB": {"type": "B777-300ER",  "seats": 355, "range_km": 13650},
    "A7-ALA": {"type": "A350-900",    "seats": 283, "range_km": 15000},
    "A7-ALB": {"type": "A350-900",    "seats": 283, "range_km": 15000},
    "A7-ALC": {"type": "A350-1000",   "seats": 327, "range_km": 16100},
    "A7-BEA": {"type": "B787-8",      "seats": 254, "range_km": 13620},
    "A7-BEB": {"type": "B787-8",      "seats": 254, "range_km": 13620},
}

# One representative crew per aircraft (simplified - real ops has many)
CREW_ASSIGNMENTS = {
    "A7-APA": "CREW-01",
    "A7-BAA": "CREW-02",
    "A7-BAB": "CREW-03",
    "A7-ALA": "CREW-04",
    "A7-ALB": "CREW-05",
    "A7-ALC": "CREW-06",
    "A7-BEA": "CREW-07",
    "A7-BEB": "CREW-08",
}


REQUIRED_COLUMNS = {
    "flight_id",
    "direction",
    "origin",
    "destination",
    "aircraft_reg",
    "aircraft_type",
    "crew_id",
    "seats",
    "load_factor",
    "pax",
    "arr_scheduled",
    "arr_actual",
    "dep_scheduled",
    "dep_actual",
    "arr_delay_min",
    "dep_delay_min",
    "status",
    "block_time_h",
}


def _fallback_for_open_sky(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize OpenSky arrivals-only payload into internal schema.
    This preserves real arrivals while avoiding KeyError crashes downstream.
    """
    if df.empty:
        return df

    fleet_regs = list(QR_FLEET.keys())
    crews = list(CREW_ASSIGNMENTS.values())

    normalized = df.copy()
    normalized["flight_id"] = normalized["flight_id"].fillna("QTRUNK").astype(str)
    normalized["direction"] = "inbound"
    normalized["origin"] = normalized.get("origin", "UNKN").fillna("UNKN")
    normalized["destination"] = normalized.get("destination", OTHH).fillna(OTHH)

    # OpenSky often returns transponder hex in icao24; map unknown/non-QR regs to representative fleet regs.
    regs_series = normalized["aircraft_reg"] if "aircraft_reg" in normalized.columns else pd.Series([None] * len(normalized))
    mapped_regs = []
    for idx, reg in enumerate(regs_series):
        reg_str = str(reg).upper() if pd.notna(reg) else ""
        if reg_str in QR_FLEET:
            mapped_regs.append(reg_str)
        else:
            mapped_regs.append(fleet_regs[idx % len(fleet_regs)])
    normalized["aircraft_reg"] = mapped_regs

    normalized["aircraft_type"] = normalized["aircraft_reg"].map(lambda r: QR_FLEET[r]["type"])
    normalized["crew_id"] = [crews[i % len(crews)] for i in range(len(normalized))]
    normalized["seats"] = normalized["aircraft_reg"].map(lambda r: QR_FLEET[r]["seats"])
    normalized["load_factor"] = 0.85
    normalized["pax"] = (normalized["seats"] * normalized["load_factor"]).astype(int)

    normalized["arr_scheduled"] = normalized.get("arr_scheduled", normalized["arr_actual"])
    normalized["arr_actual"] = pd.to_datetime(normalized["arr_actual"], utc=True, errors="coerce")
    normalized["arr_scheduled"] = pd.to_datetime(normalized["arr_scheduled"], utc=True, errors="coerce")
    normalized["dep_scheduled"] = pd.NaT
    normalized["dep_actual"] = pd.NaT
    normalized["arr_delay_min"] = (
        (normalized["arr_actual"] - normalized["arr_scheduled"]).dt.total_seconds() / 60
    ).fillna(0.0).round(1)
    normalized["dep_delay_min"] = 0.0
    normalized["status"] = "landed"
    normalized["block_time_h"] = 6.0
    normalized["turnaround_slack_min"] = 0.0
    return normalized


def _schedule_is_usable(df: pd.DataFrame) -> bool:
    """
    Return True only if schedule supports dependency construction.
    Current model requires both inbound and outbound flights.
    """
    if df is None or df.empty:
        return False
    if not REQUIRED_COLUMNS.issubset(df.columns):
        return False
    has_inbound = (df["direction"] == "inbound").any()
    has_outbound = (df["direction"] == "outbound").any()
    return bool(has_inbound and has_outbound)


def fetch_from_opensky(date: datetime) -> pd.DataFrame | None:
    """
    Pull real arrival data from OpenSky Network for DOH.
    Returns DataFrame or None if unavailable (rate-limited / no network).
    Free API: 400 calls/day unauthenticated.
    """
    start = int(date.replace(hour=0,  minute=0,  second=0,  tzinfo=timezone.utc).timestamp())
    end   = int(date.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc).timestamp())

    try:
        resp = requests.get(
            OPENSKY_URL,
            params={"airport": OTHH, "begin": start, "end": end},
            timeout=10
        )
        resp.raise_for_status()
        raw = resp.json()

        if not raw:
            return None

        flights = []
        for f in raw:
            callsign = (f.get("callsign") or "").strip()
            if not callsign.startswith("QTR"):   # Qatar Airways ICAO prefix
                continue
            flights.append({
                "flight_id":   callsign,
                "callsign":    callsign,
                "origin":      f.get("estDepartureAirport", "UNKN"),
                "destination": OTHH,
                "arr_scheduled": datetime.fromtimestamp(f["lastSeen"], tz=timezone.utc),
                "arr_actual":    datetime.fromtimestamp(f["lastSeen"], tz=timezone.utc),
                "aircraft_reg":  f.get("icao24", "A7-UNK").upper(),
                "direction":     "inbound",
            })

        if not flights:
            return None
        return _fallback_for_open_sky(pd.DataFrame(flights))

    except Exception as exc:
        logger.warning("OpenSky unavailable (%s). Using synthetic data.", exc)
        return None


def build_synthetic_schedule(base_date: datetime | None = None) -> pd.DataFrame:
    """
    Synthetic one-day DOH schedule built from real QR flight numbers,
    real route distances, and realistic hub-wave timing.

    Structure:
      - Wave 1 arrivals  04:00–07:00  (long-haul overnights from US/Europe)
      - Wave 1 departures 07:00–09:30 (these aircraft rotate out to Asia/short-haul)
      - Wave 2 arrivals  09:00–13:00  (Asia, Africa, short-haul)
      - Wave 2 departures 13:00–16:30
      - Wave 3 arrivals  17:00–21:00  (Europe afternoon, more Asia)
      - Wave 3 departures 21:00–23:59

    Each aircraft does one inbound + one outbound rotation for simplicity.
    Load factors drawn from a truncated normal (μ=0.85, σ=0.08).
    """
    if base_date is None:
        base_date = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def t(h, m):
        return base_date + timedelta(hours=h, minutes=m)

    rng = np.random.default_rng(seed=42)

    def lf():
        return float(np.clip(rng.normal(0.85, 0.08), 0.60, 1.0))

    # ── Inbound flights ────────────────────────────────────────────────────────
    inbound = [
        # Wave 1 – long haul overnights (arrive 06:20–07:30, tight window)
        {"flight_id": "QR007",  "origin": "EGLL", "dest": "OTHH", "aircraft": "A7-BAA",
         "arr_sched": t(6, 20),  "duration_h": 7.0,  "seats": 355, "lf": lf()},
        {"flight_id": "QR021",  "origin": "KJFK", "dest": "OTHH", "aircraft": "A7-ALC",
         "arr_sched": t(6, 50),  "duration_h": 14.0, "seats": 327, "lf": lf()},
        {"flight_id": "QR052",  "origin": "LFPG", "dest": "OTHH", "aircraft": "A7-ALA",
         "arr_sched": t(7, 10),  "duration_h": 6.5,  "seats": 283, "lf": lf()},
        {"flight_id": "QR068",  "origin": "EDDF", "dest": "OTHH", "aircraft": "A7-ALB",
         "arr_sched": t(7, 30),  "duration_h": 5.75, "seats": 283, "lf": lf()},
        # Wave 2 – Asia/Africa midday
        {"flight_id": "QR402",  "origin": "VTBS", "dest": "OTHH", "aircraft": "A7-BEA",
         "arr_sched": t(9, 20),  "duration_h": 6.0,  "seats": 254, "lf": lf()},
        {"flight_id": "QR502",  "origin": "WSSS", "dest": "OTHH", "aircraft": "A7-BEB",
         "arr_sched": t(10, 5),  "duration_h": 7.25, "seats": 254, "lf": lf()},
        {"flight_id": "QR548",  "origin": "VABB", "dest": "OTHH", "aircraft": "A7-APA",
         "arr_sched": t(11, 0),  "duration_h": 3.25, "seats": 517, "lf": lf()},
        {"flight_id": "QR842",  "origin": "WMKK", "dest": "OTHH", "aircraft": "A7-BAB",
         "arr_sched": t(12, 30), "duration_h": 8.5,  "seats": 355, "lf": lf()},
    ]

    # ── Outbound flights — tight turnarounds (55–75 min) to ensure realistic cascades
    outbound = [
        # Wave 1 rotations — ~60 min turnaround → slack 10–20 min above MIN
        {"flight_id": "QR008",  "origin": "OTHH", "dest": "EGLL", "aircraft": "A7-BAA",
         "dep_sched": t(7, 25),  "duration_h": 7.0,  "seats": 355, "lf": lf()},  # 65m from QR007 arr
        {"flight_id": "QR020",  "origin": "OTHH", "dest": "KJFK", "aircraft": "A7-ALC",
         "dep_sched": t(8, 0),   "duration_h": 14.0, "seats": 327, "lf": lf()},  # 70m from QR021 arr
        {"flight_id": "QR051",  "origin": "OTHH", "dest": "LFPG", "aircraft": "A7-ALA",
         "dep_sched": t(8, 15),  "duration_h": 6.5,  "seats": 283, "lf": lf()},  # 65m from QR052 arr
        {"flight_id": "QR067",  "origin": "OTHH", "dest": "EDDF", "aircraft": "A7-ALB",
         "dep_sched": t(8, 30),  "duration_h": 5.75, "seats": 283, "lf": lf()},  # 60m from QR068 arr
        # Wave 2 rotations — 60–70 min turnaround
        {"flight_id": "QR401",  "origin": "OTHH", "dest": "VTBS", "aircraft": "A7-BEA",
         "dep_sched": t(10, 30), "duration_h": 6.0,  "seats": 254, "lf": lf()},  # 70m from QR402 arr
        {"flight_id": "QR501",  "origin": "OTHH", "dest": "WSSS", "aircraft": "A7-BEB",
         "dep_sched": t(11, 10), "duration_h": 7.25, "seats": 254, "lf": lf()},  # 65m from QR502 arr
        {"flight_id": "QR547",  "origin": "OTHH", "dest": "VABB", "aircraft": "A7-APA",
         "dep_sched": t(12, 10), "duration_h": 3.25, "seats": 517, "lf": lf()},  # 70m from QR548 arr
        {"flight_id": "QR841",  "origin": "OTHH", "dest": "WMKK", "aircraft": "A7-BAB",
         "dep_sched": t(13, 30), "duration_h": 8.5,  "seats": 355, "lf": lf()},  # 60m from QR842 arr
    ]

    rows = []

    for f in inbound:
        arr_actual = f["arr_sched"] + timedelta(minutes=int(rng.integers(-5, 15)))
        rows.append({
            "flight_id":        f["flight_id"],
            "direction":        "inbound",
            "origin":           f["origin"],
            "destination":      "OTHH",
            "aircraft_reg":     f["aircraft"],
            "aircraft_type":    QR_FLEET[f["aircraft"]]["type"],
            "crew_id":          CREW_ASSIGNMENTS[f["aircraft"]],
            "seats":            f["seats"],
            "load_factor":      round(f["lf"], 3),
            "pax":              int(f["seats"] * f["lf"]),
            "arr_scheduled":    f["arr_sched"],
            "arr_actual":       arr_actual,
            "dep_scheduled":    pd.NaT,
            "dep_actual":       pd.NaT,
            "arr_delay_min":    round((arr_actual - f["arr_sched"]).total_seconds() / 60, 1),
            "dep_delay_min":    0.0,
            "status":           "landed",
            "block_time_h":     f["duration_h"],
        })

    for f in outbound:
        rows.append({
            "flight_id":        f["flight_id"],
            "direction":        "outbound",
            "origin":           "OTHH",
            "destination":      f["dest"],
            "aircraft_reg":     f["aircraft"],
            "aircraft_type":    QR_FLEET[f["aircraft"]]["type"],
            "crew_id":          CREW_ASSIGNMENTS[f["aircraft"]],
            "seats":            f["seats"],
            "load_factor":      round(f["lf"], 3),
            "pax":              int(f["seats"] * f["lf"]),
            "arr_scheduled":    pd.NaT,
            "arr_actual":       pd.NaT,
            "dep_scheduled":    f["dep_sched"],
            "dep_actual":       f["dep_sched"],          # starts on-time; cascade will change this
            "arr_delay_min":    0.0,
            "dep_delay_min":    0.0,
            "status":           "scheduled",
            "block_time_h":     f["duration_h"],
        })

    df = pd.DataFrame(rows)

    # Build rotation pairs: each inbound aircraft → its outbound rotation
    # turnaround_slack = dep_scheduled - arr_actual - MIN_TURNAROUND
    inb = df[df["direction"] == "inbound"].set_index("aircraft_reg")
    oub = df[df["direction"] == "outbound"].set_index("aircraft_reg")

    for reg in inb.index:
        if reg in oub.index:
            arr = inb.loc[reg, "arr_actual"]
            dep = oub.loc[reg, "dep_scheduled"]
            slack = (dep - arr).total_seconds() / 60 - MIN_TURNAROUND_MINUTES
            df.loc[df["aircraft_reg"] == reg, "turnaround_slack_min"] = round(slack, 1)

    df["turnaround_slack_min"] = df.get("turnaround_slack_min", pd.Series(dtype=float)).fillna(0)
    df = df.reset_index(drop=True)
    return df


def load_schedule(date: datetime | None = None, use_opensky: bool = True) -> pd.DataFrame:
    """
    Public entry point. Returns a clean schedule DataFrame.
    Tries OpenSky first; falls back to synthetic if unavailable.
    """
    if date is None:
        date = datetime.now(tz=timezone.utc)

    if use_opensky:
        df = fetch_from_opensky(date)
        if df is not None and len(df) > 5 and _schedule_is_usable(df):
            logger.info("Loaded %d flights from OpenSky.", len(df))
            return df
        if df is not None and len(df) > 0:
            logger.info(
                "OpenSky payload incomplete for cascade model (arrivals-only or missing fields). "
                "Using synthetic schedule."
            )
        else:
            logger.info("Using synthetic schedule.")

    return build_synthetic_schedule(date)
