"""
data_loader.py
--------------
Loads a day's worth of Qatar Airways flights at Hamad International (DOH/OTHH).

Primary:   OpenSky Network REST API (free, real historical data)
Fallback:  Synthetic schedule built from real QR routes + realistic timing
"""

from __future__ import annotations

import warnings
warnings.filterwarnings(
    "ignore",
    message="urllib3 .* doesn't match a supported version!",
    module="requests",
)
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Any

import numpy as np
import pandas as pd
import requests

from engine.config import (
    DATA_FRESHNESS_DEGRADE_SECONDS,
    DATA_FRESHNESS_WARN_SECONDS,
    MIN_TURNAROUND_MINUTES,
    OPENSKY_CIRCUIT_FAILURE_THRESHOLD,
    OPENSKY_CIRCUIT_RESET_SECONDS,
    OPENSKY_MAX_RETRIES,
    OPENSKY_RETRY_BACKOFF_SECONDS,
    OPENSKY_TIMEOUT_SECONDS,
    OPENSKY_URL,
    OTHH,
)

logger = logging.getLogger(__name__)
REQUEST_HEADERS = {"User-Agent": "SILSILA/1.0 (educational ops simulator)"}
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class FeedCircuitBreaker:
    failure_threshold: int
    reset_timeout_s: int
    failure_count: int = 0
    opened_at: datetime | None = None

    def allow_request(self, now: datetime) -> bool:
        if self.opened_at is None:
            return True
        elapsed = (now - self.opened_at).total_seconds()
        if elapsed >= self.reset_timeout_s:
            self.opened_at = None
            self.failure_count = 0
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self, now: datetime) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = now

    def state(self, now: datetime) -> str:
        if self.opened_at is None:
            return "CLOSED"
        elapsed = (now - self.opened_at).total_seconds()
        return "HALF_OPEN" if elapsed >= self.reset_timeout_s else "OPEN"


_OPENSKY_CIRCUIT = FeedCircuitBreaker(
    failure_threshold=OPENSKY_CIRCUIT_FAILURE_THRESHOLD,
    reset_timeout_s=OPENSKY_CIRCUIT_RESET_SECONDS,
)
_LAST_FEED_METADATA: dict[str, Any] = {}

# Real Qatar Airways fleet sample (tail -> aircraft type -> seats)
QR_FLEET = {
    "A7-APA": {"type": "A380-800", "seats": 517, "range_km": 15200},
    "A7-BAA": {"type": "B777-300ER", "seats": 355, "range_km": 13650},
    "A7-BAB": {"type": "B777-300ER", "seats": 355, "range_km": 13650},
    "A7-ALA": {"type": "A350-900", "seats": 283, "range_km": 15000},
    "A7-ALB": {"type": "A350-900", "seats": 283, "range_km": 15000},
    "A7-ALC": {"type": "A350-1000", "seats": 327, "range_km": 16100},
    "A7-BEA": {"type": "B787-8", "seats": 254, "range_km": 13620},
    "A7-BEB": {"type": "B787-8", "seats": 254, "range_km": 13620},
}

# One representative crew per aircraft (simplified - real ops has many)
CREW_ASSIGNMENTS = {
    "A7-APA": "CREW-01",
    "A7-ALC": "CREW-01",
    "A7-BAA": "CREW-02",
    "A7-BAB": "CREW-02",
    "A7-ALA": "CREW-04",
    "A7-ALB": "CREW-04",
    "A7-BEA": "CREW-07",
    "A7-BEB": "CREW-07",
}

SYNTHETIC_ROTATIONS = [
    {
        "aircraft": "A7-BAA",
        "origin": "EGLL",
        "duration_h": 7.0,
        "arrivals": [("QR007", 6, 20), ("QR107", None, None)],
        "departures": [("QR008", None, None), ("QR108", None, None)],
        "turn_buffer_1": 20,
        "remote_buffer": 25,
        "turn_buffer_2": 12,
    },
    {
        "aircraft": "A7-ALC",
        "origin": "KJFK",
        "duration_h": 14.0,
        "arrivals": [("QR021", 6, 50), ("QR121", None, None)],
        "departures": [("QR020", None, None), ("QR120", None, None)],
        "turn_buffer_1": 25,
        "remote_buffer": 30,
        "turn_buffer_2": 15,
    },
    {
        "aircraft": "A7-ALA",
        "origin": "LFPG",
        "duration_h": 6.5,
        "arrivals": [("QR052", 7, 10), ("QR152", None, None)],
        "departures": [("QR051", None, None), ("QR151", None, None)],
        "turn_buffer_1": 20,
        "remote_buffer": 22,
        "turn_buffer_2": 14,
    },
    {
        "aircraft": "A7-ALB",
        "origin": "EDDF",
        "duration_h": 5.75,
        "arrivals": [("QR068", 7, 30), ("QR168", None, None)],
        "departures": [("QR067", None, None), ("QR167", None, None)],
        "turn_buffer_1": 15,
        "remote_buffer": 18,
        "turn_buffer_2": 10,
    },
    {
        "aircraft": "A7-BEA",
        "origin": "VTBS",
        "duration_h": 6.0,
        "arrivals": [("QR402", 9, 20), ("QR452", None, None)],
        "departures": [("QR401", None, None), ("QR451", None, None)],
        "turn_buffer_1": 22,
        "remote_buffer": 20,
        "turn_buffer_2": 12,
    },
    {
        "aircraft": "A7-BEB",
        "origin": "WSSS",
        "duration_h": 7.25,
        "arrivals": [("QR502", 10, 5), ("QR552", None, None)],
        "departures": [("QR501", None, None), ("QR551", None, None)],
        "turn_buffer_1": 20,
        "remote_buffer": 26,
        "turn_buffer_2": 14,
    },
    {
        "aircraft": "A7-APA",
        "origin": "VABB",
        "duration_h": 3.25,
        "arrivals": [("QR548", 11, 0), ("QR648", None, None)],
        "departures": [("QR547", None, None), ("QR647", None, None)],
        "turn_buffer_1": 25,
        "remote_buffer": 16,
        "turn_buffer_2": 10,
    },
    {
        "aircraft": "A7-BAB",
        "origin": "WMKK",
        "duration_h": 8.5,
        "arrivals": [("QR842", 12, 30), ("QR942", None, None)],
        "departures": [("QR841", None, None), ("QR941", None, None)],
        "turn_buffer_1": 15,
        "remote_buffer": 24,
        "turn_buffer_2": 12,
    },
]

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
    "turnaround_slack_min",
}


def _ingestion_metadata(
    *,
    provider: str,
    outcome: str,
    mode: str,
    attempts: int,
    status_code: int | None = None,
    error: str = "",
    records_received: int = 0,
    latency_ms: float = 0.0,
    circuit_state: str = "CLOSED",
    timeout_s: int = OPENSKY_TIMEOUT_SECONDS,
    max_retries: int = OPENSKY_MAX_RETRIES,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "outcome": outcome,
        "mode": mode,
        "attempts": attempts,
        "status_code": status_code,
        "error": error,
        "records_received": records_received,
        "latency_ms": round(float(latency_ms), 1),
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "circuit_state": circuit_state,
        "timeout_s": timeout_s,
        "max_retries": max_retries,
        "freshness_warn_s": DATA_FRESHNESS_WARN_SECONDS,
        "freshness_degrade_s": DATA_FRESHNESS_DEGRADE_SECONDS,
        "fallback_active": mode == "FALLBACK",
    }



def _remember_feed_metadata(meta: dict[str, Any]) -> None:
    global _LAST_FEED_METADATA
    _LAST_FEED_METADATA = dict(meta)



def get_last_feed_metadata() -> dict[str, Any]:
    return dict(_LAST_FEED_METADATA)



def _stamp_schedule(df: pd.DataFrame, data_source: str, ingestion_meta: dict[str, Any], degraded_reasons: list[str] | None = None) -> pd.DataFrame:
    df.attrs["data_source"] = data_source
    df.attrs["ingestion_metadata"] = dict(ingestion_meta)
    df.attrs["loaded_at"] = datetime.now(tz=timezone.utc).isoformat()
    df.attrs["degraded_reasons"] = list(degraded_reasons or [])
    df.attrs["fallback_active"] = bool(ingestion_meta.get("fallback_active", False))
    return df



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
    normalized.attrs["data_source"] = "opensky-arrivals-partial"
    return normalized



def _schedule_is_usable(df: pd.DataFrame) -> bool:
    """Return True only if schedule supports dependency construction."""
    if df is None or df.empty:
        return False
    if not REQUIRED_COLUMNS.issubset(df.columns):
        return False
    has_inbound = (df["direction"] == "inbound").any()
    has_outbound = (df["direction"] == "outbound").any()
    return bool(has_inbound and has_outbound)



def _rotation_reference_time(row: pd.Series):
    return row["arr_actual"] if row["direction"] == "inbound" else row["dep_scheduled"]



def _apply_turnaround_slack(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute slack for each sequential same-aircraft rotation leg."""
    df = df.copy()
    df["turnaround_slack_min"] = 0.0

    for _, group in df.groupby("aircraft_reg"):
        ordered = group.copy()
        ordered["_ref_time"] = ordered.apply(_rotation_reference_time, axis=1)
        ordered = ordered.sort_values("_ref_time")
        ordered_rows = list(ordered.iterrows())

        for pos in range(len(ordered_rows) - 1):
            current_idx, current = ordered_rows[pos]
            next_idx, nxt = ordered_rows[pos + 1]

            if current["direction"] == "inbound" and nxt["direction"] == "outbound":
                if pd.isna(current["arr_actual"]) or pd.isna(nxt["dep_scheduled"]):
                    continue
                slack = (nxt["dep_scheduled"] - current["arr_actual"]).total_seconds() / 60 - MIN_TURNAROUND_MINUTES
                df.loc[next_idx, "turnaround_slack_min"] = round(slack, 1)
            elif current["direction"] == "outbound" and nxt["direction"] == "inbound":
                if pd.isna(current["dep_scheduled"]) or pd.isna(nxt["arr_scheduled"]):
                    continue
                if current["destination"] != nxt["origin"]:
                    continue
                remote_cycle_min = (current["block_time_h"] + nxt["block_time_h"]) * 60 + MIN_TURNAROUND_MINUTES
                slack = (nxt["arr_scheduled"] - current["dep_scheduled"]).total_seconds() / 60 - remote_cycle_min
                df.loc[next_idx, "turnaround_slack_min"] = round(slack, 1)

    df["turnaround_slack_min"] = df["turnaround_slack_min"].fillna(0.0)
    return df



def _build_hybrid_schedule(opensky_df: pd.DataFrame, base_date: datetime) -> pd.DataFrame:
    """
    Blend real OpenSky arrivals into the modeled hub schedule so the simulator
    remains internally consistent while preserving observed arrival timing.
    """
    hybrid = build_synthetic_schedule(base_date).copy()
    real_inbound = (
        opensky_df[opensky_df["direction"] == "inbound"]
        .dropna(subset=["arr_actual"])
        .sort_values(["arr_actual", "flight_id"])
        .reset_index(drop=True)
    )
    hybrid_inbound_idx = list(hybrid.index[hybrid["direction"] == "inbound"])

    if not hybrid_inbound_idx or real_inbound.empty:
        return hybrid

    assigned = min(len(hybrid_inbound_idx), len(real_inbound))
    for pos in range(assigned):
        idx = hybrid_inbound_idx[pos]
        real_row = real_inbound.iloc[pos]
        hybrid.loc[idx, "flight_id"] = real_row["flight_id"]
        hybrid.loc[idx, "origin"] = real_row["origin"]
        hybrid.loc[idx, "destination"] = OTHH
        hybrid.loc[idx, "arr_scheduled"] = real_row["arr_scheduled"]
        hybrid.loc[idx, "arr_actual"] = real_row["arr_actual"]
        hybrid.loc[idx, "arr_delay_min"] = real_row["arr_delay_min"]
        hybrid.loc[idx, "status"] = "landed"

    hybrid = _apply_turnaround_slack(hybrid)
    hybrid.attrs["data_source"] = f"opensky-hybrid-{assigned}-arrivals"
    return hybrid



def _fetch_json_with_retries(url: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    now = datetime.now(tz=timezone.utc)
    if not _OPENSKY_CIRCUIT.allow_request(now):
        meta = _ingestion_metadata(
            provider="opensky",
            outcome="CIRCUIT_OPEN",
            mode="FALLBACK",
            attempts=0,
            error="OpenSky circuit breaker is open after repeated upstream failures.",
            circuit_state=_OPENSKY_CIRCUIT.state(now),
        )
        _remember_feed_metadata(meta)
        return None, meta

    attempts = 0
    last_error = ""
    status_code = None
    t0 = time.perf_counter()
    session = requests.Session()
    try:
        for attempts in range(1, OPENSKY_MAX_RETRIES + 2):
            try:
                response = session.get(
                    url,
                    params=params,
                    headers=REQUEST_HEADERS,
                    timeout=OPENSKY_TIMEOUT_SECONDS,
                )
                status_code = response.status_code
                if response.status_code in RETRIABLE_STATUS_CODES and attempts <= OPENSKY_MAX_RETRIES:
                    time.sleep(OPENSKY_RETRY_BACKOFF_SECONDS * attempts)
                    continue
                response.raise_for_status()
                payload = response.json()
                meta = _ingestion_metadata(
                    provider="opensky",
                    outcome="SUCCESS" if payload else "EMPTY",
                    mode="LIVE",
                    attempts=attempts,
                    status_code=status_code,
                    records_received=len(payload or []),
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    circuit_state=_OPENSKY_CIRCUIT.state(datetime.now(tz=timezone.utc)),
                )
                _OPENSKY_CIRCUIT.record_success()
                _remember_feed_metadata(meta)
                return payload, meta
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempts <= OPENSKY_MAX_RETRIES:
                    time.sleep(OPENSKY_RETRY_BACKOFF_SECONDS * attempts)
                    continue
    finally:
        session.close()

    failure_now = datetime.now(tz=timezone.utc)
    _OPENSKY_CIRCUIT.record_failure(failure_now)
    meta = _ingestion_metadata(
        provider="opensky",
        outcome="ERROR",
        mode="FALLBACK",
        attempts=attempts,
        status_code=status_code,
        error=last_error,
        latency_ms=(time.perf_counter() - t0) * 1000,
        circuit_state=_OPENSKY_CIRCUIT.state(failure_now),
    )
    _remember_feed_metadata(meta)
    return None, meta



def fetch_from_opensky(date: datetime) -> pd.DataFrame | None:
    """
    Pull real arrival data from OpenSky Network for DOH.
    Returns DataFrame or None if unavailable (rate-limited / no network).
    Free API: 400 calls/day unauthenticated.
    """
    start = int(date.replace(hour=0, minute=0, second=0, tzinfo=timezone.utc).timestamp())
    end = int(date.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc).timestamp())

    raw, meta = _fetch_json_with_retries(
        OPENSKY_URL,
        {"airport": OTHH, "begin": start, "end": end},
    )
    if not raw:
        if meta.get("outcome") == "ERROR":
            logger.warning("OpenSky unavailable (%s). Using fallback schedule.", meta.get("error", "unknown error"))
        elif meta.get("outcome") == "CIRCUIT_OPEN":
            logger.warning("OpenSky circuit breaker open. Using fallback schedule.")
        return None

    flights = []
    for flight in raw:
        callsign = (flight.get("callsign") or "").strip()
        if not callsign.startswith("QTR"):
            continue
        flights.append(
            {
                "flight_id": callsign,
                "callsign": callsign,
                "origin": flight.get("estDepartureAirport", "UNKN"),
                "destination": OTHH,
                "arr_scheduled": datetime.fromtimestamp(flight["lastSeen"], tz=timezone.utc),
                "arr_actual": datetime.fromtimestamp(flight["lastSeen"], tz=timezone.utc),
                "aircraft_reg": flight.get("icao24", "A7-UNK").upper(),
                "direction": "inbound",
            }
        )

    if not flights:
        empty_meta = dict(meta)
        empty_meta["outcome"] = "EMPTY"
        empty_meta["records_received"] = 0
        _remember_feed_metadata(empty_meta)
        return None

    normalized = _fallback_for_open_sky(pd.DataFrame(flights))
    normalized = _stamp_schedule(normalized, "opensky-arrivals-partial", meta)
    return normalized



def build_synthetic_schedule(base_date: datetime | None = None) -> pd.DataFrame:
    """
    Synthetic DOH schedule built from representative QR routes and chained rotations.

    Each modeled aircraft performs two full rotations:
      inbound_1 -> outbound_1 -> return_inbound_2 -> outbound_2

    This creates genuine multi-hop aircraft chains so a disruption can propagate
    across more than one turn instead of stopping after the first hub departure.
    """
    if base_date is None:
        base_date = datetime.now(tz=timezone.utc)
    base_date = base_date.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def clock(hour: int, minute: int):
        return base_date + timedelta(hours=hour, minutes=minute)

    rng = np.random.default_rng(seed=42)

    def load_factor() -> float:
        return float(np.clip(rng.normal(0.85, 0.08), 0.60, 1.0))

    rows = []
    for template in SYNTHETIC_ROTATIONS:
        aircraft = template["aircraft"]
        seats = QR_FLEET[aircraft]["seats"]
        duration_h = float(template["duration_h"])
        duration_min = duration_h * 60
        origin = template["origin"]

        arr1_sched = clock(template["arrivals"][0][1], template["arrivals"][0][2])
        dep1_sched = arr1_sched + timedelta(minutes=MIN_TURNAROUND_MINUTES + template["turn_buffer_1"])
        arr2_sched = dep1_sched + timedelta(minutes=(duration_min * 2) + MIN_TURNAROUND_MINUTES + template["remote_buffer"])
        dep2_sched = arr2_sched + timedelta(minutes=MIN_TURNAROUND_MINUTES + template["turn_buffer_2"])

        inbound_specs = [
            (template["arrivals"][0][0], arr1_sched),
            (template["arrivals"][1][0], arr2_sched),
        ]
        outbound_specs = [
            (template["departures"][0][0], dep1_sched),
            (template["departures"][1][0], dep2_sched),
        ]

        for flight_id, arr_sched in inbound_specs:
            lf = load_factor()
            arr_actual = arr_sched + timedelta(minutes=int(rng.integers(-5, 15)))
            rows.append(
                {
                    "flight_id": flight_id,
                    "direction": "inbound",
                    "origin": origin,
                    "destination": OTHH,
                    "aircraft_reg": aircraft,
                    "aircraft_type": QR_FLEET[aircraft]["type"],
                    "crew_id": CREW_ASSIGNMENTS[aircraft],
                    "seats": seats,
                    "load_factor": round(lf, 3),
                    "pax": int(seats * lf),
                    "arr_scheduled": arr_sched,
                    "arr_actual": arr_actual,
                    "dep_scheduled": pd.NaT,
                    "dep_actual": pd.NaT,
                    "arr_delay_min": round((arr_actual - arr_sched).total_seconds() / 60, 1),
                    "dep_delay_min": 0.0,
                    "status": "landed",
                    "block_time_h": duration_h,
                }
            )

        for flight_id, dep_sched in outbound_specs:
            lf = load_factor()
            rows.append(
                {
                    "flight_id": flight_id,
                    "direction": "outbound",
                    "origin": OTHH,
                    "destination": origin,
                    "aircraft_reg": aircraft,
                    "aircraft_type": QR_FLEET[aircraft]["type"],
                    "crew_id": CREW_ASSIGNMENTS[aircraft],
                    "seats": seats,
                    "load_factor": round(lf, 3),
                    "pax": int(seats * lf),
                    "arr_scheduled": pd.NaT,
                    "arr_actual": pd.NaT,
                    "dep_scheduled": dep_sched,
                    "dep_actual": dep_sched,
                    "arr_delay_min": 0.0,
                    "dep_delay_min": 0.0,
                    "status": "scheduled",
                    "block_time_h": duration_h,
                }
            )

    df = pd.DataFrame(rows)
    df = _apply_turnaround_slack(df)
    df = df.reset_index(drop=True)
    synthetic_meta = _ingestion_metadata(
        provider="synthetic",
        outcome="SYNTHETIC",
        mode="FALLBACK",
        attempts=0,
        records_received=len(df),
        circuit_state=_OPENSKY_CIRCUIT.state(datetime.now(tz=timezone.utc)),
    )
    synthetic_meta["fallback_active"] = True
    synthetic_meta["error"] = "Synthetic fallback schedule generated locally."
    return _stamp_schedule(df, "synthetic-hub-schedule", synthetic_meta, degraded_reasons=["Synthetic fallback schedule is active."])



def _complete_hybrid_ingestion_meta(base_meta: dict[str, Any], assigned: int) -> dict[str, Any]:
    hybrid_meta = dict(base_meta)
    hybrid_meta["outcome"] = "HYBRID"
    hybrid_meta["mode"] = "HYBRID"
    hybrid_meta["fallback_active"] = False
    hybrid_meta["records_received"] = assigned
    return hybrid_meta



def load_schedule(date: datetime | None = None, use_opensky: bool = True) -> pd.DataFrame:
    """
    Public entry point. Returns a clean schedule DataFrame.
    Tries OpenSky first; falls back to synthetic if unavailable.
    """
    if date is None:
        date = datetime.now(tz=timezone.utc)

    if use_opensky:
        df = fetch_from_opensky(date)
        ingestion_meta = (df.attrs.get("ingestion_metadata") if df is not None else None) or get_last_feed_metadata()
        if df is not None and len(df) > 5:
            if _schedule_is_usable(df):
                logger.info("Loaded %d flights from OpenSky.", len(df))
                return _stamp_schedule(df, df.attrs.get("data_source", "opensky-arrivals-partial"), ingestion_meta)

            hybrid = _build_hybrid_schedule(df, date)
            if _schedule_is_usable(hybrid):
                assigned = int((df["direction"] == "inbound").sum())
                logger.info("Blended %d OpenSky arrivals into the modeled hub schedule.", assigned)
                hybrid_meta = _complete_hybrid_ingestion_meta(ingestion_meta, assigned)
                return _stamp_schedule(
                    hybrid,
                    hybrid.attrs.get("data_source", f"opensky-hybrid-{assigned}-arrivals"),
                    hybrid_meta,
                    degraded_reasons=["Hybrid schedule blends authoritative arrivals with modeled downstream legs."],
                )

        fallback_reasons = []
        if ingestion_meta.get("error"):
            fallback_reasons.append(ingestion_meta["error"])
        if ingestion_meta.get("outcome") == "CIRCUIT_OPEN":
            fallback_reasons.append("OpenSky circuit breaker open after repeated failures.")
        if not fallback_reasons:
            fallback_reasons.append("OpenSky data unavailable or incomplete; using synthetic schedule.")
        logger.info("Using synthetic schedule.")
        synthetic = build_synthetic_schedule(date)
        synthetic_meta = dict(ingestion_meta) if ingestion_meta else synthetic.attrs.get("ingestion_metadata", {})
        synthetic_meta.update({
            "provider": synthetic_meta.get("provider", "opensky"),
            "mode": "FALLBACK",
            "fallback_active": True,
        })
        return _stamp_schedule(synthetic, "synthetic-hub-schedule", synthetic_meta, degraded_reasons=fallback_reasons)

    synthetic = build_synthetic_schedule(date)
    return synthetic
