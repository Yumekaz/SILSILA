"""
recovery.py
-----------
Phase 2: Three recovery heuristics for flight disruption management.

Based on standard airline IROPS (Irregular Operations) decision framework.
Literature basis: Rosenberger et al. (2003), Bratu & Barnhart (2006),
                  ScienceDirect review 2024 — delay/cancel/swap are the
                  three primary levers in real ops.

Each heuristic takes:
  - The NetworkX graph G
  - The schedule DataFrame
  - The CascadeResult from Phase 1

Each heuristic returns a RecoveryOption dataclass with:
  - Strategy name, description, feasibility flag
  - Delay reduction vs no-action baseline
  - Passengers saved, pax stranded
  - Total estimated cost
  - Modified schedule (for Gantt re-render)
  - Action log (human-readable steps taken)
"""

import pandas as pd
import networkx as nx
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from engine.config import (
    COST_PAX_PER_MIN,
    COST_AIRCRAFT_PER_MIN,
    MIN_TURNAROUND_MINUTES,
    SPARE_AIRCRAFT_POOL,
    SWAP_POSITIONING_COST,
    SWAP_READINESS_MINUTES,
    CANCEL_REBOOKING_COST_PER_PAX,
    CANCEL_EU261_THRESHOLD_MIN,
    CANCEL_EU261_COST_PER_PAX,
    COMPRESS_TURNAROUND_MINUTES,
)
from engine.cascade import CascadeResult, run_cascade


# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RecoveryOption:
    """Full output of one recovery heuristic evaluation."""
    strategy:           str           # "SWAP" | "DELAY" | "CANCEL"
    label:              str           # Short display name
    description:        str           # 1-sentence plain-English description
    feasible:           bool          # Can this actually be executed?
    infeasibility_reason: str = ""    # Why not, if infeasible

    # vs. no-action baseline
    baseline_delay_min:   float = 0.0   # Total cascade delay WITHOUT recovery
    recovered_delay_min:  float = 0.0   # Total cascade delay WITH this recovery
    delay_reduction_min:  float = 0.0   # baseline - recovered (higher = better)
    delay_reduction_pct:  float = 0.0   # % reduction

    # Passenger impact
    baseline_pax_affected:  int = 0
    recovered_pax_affected: int = 0
    pax_saved:              int = 0
    pax_stranded:           int = 0

    # Cost
    direct_cost_usd:    float = 0.0   # Cost of executing this recovery action
    cascade_cost_saved: float = 0.0   # Cascade cost avoided by recovery
    net_cost_usd:       float = 0.0   # direct_cost - cascade_cost_saved (lower = better)

    # Score (0–100, higher = better overall option)
    score:              float = 0.0

    # Modified schedule for Gantt re-render
    df_recovered:       Optional[object] = None   # pd.DataFrame

    # Human-readable steps taken
    action_log:         list = field(default_factory=list)

    # Which flights are still delayed (residual cascade)
    residual_events:    list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _baseline_cascade_cost(result: CascadeResult) -> float:
    """Total cost of doing nothing — direct sum of cascade event costs."""
    return result.total_cost_usd


def _flight_row(df: pd.DataFrame, flight_id: str) -> Optional[pd.Series]:
    mask = df["flight_id"] == flight_id
    if not mask.any():
        return None
    return df[mask].iloc[0]


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic 1: SWAP
# Replace the delayed aircraft with a spare from the DOH ground pool.
# Eliminates ROTATION cascade entirely. PAX_CNXN disruption remains.
# ─────────────────────────────────────────────────────────────────────────────

def heuristic_swap(
    G: nx.DiGraph,
    df: pd.DataFrame,
    result: CascadeResult,
) -> RecoveryOption:
    """
    SWAP: Substitute a ground-spare aircraft for the delayed inbound.

    Logic:
    1. Check spare pool availability (config: SPARE_AIRCRAFT_POOL)
    2. Spare ready in SWAP_READINESS_MINUTES from now
    3. ROTATION edges from trigger → all successors now use spare's clock
       (spare arrives fresh, so turnaround starts from readiness time)
    4. PAX_CNXN delays survive (passengers already missed connections)
    5. Cost = SWAP_POSITIONING_COST + any residual delay minutes still incurred
    """
    trigger_id  = result.trigger_flight
    trigger_row = _flight_row(df, trigger_id)

    # ── Feasibility check ────────────────────────────────────────────────────
    if SPARE_AIRCRAFT_POOL < 1:
        return RecoveryOption(
            strategy="SWAP", label="Aircraft Swap", feasible=False,
            description="Replace delayed aircraft with ground spare.",
            infeasibility_reason="No spare aircraft available at DOH.",
            baseline_delay_min=result.total_delay_min,
            baseline_pax_affected=result.total_pax_affected,
            direct_cost_usd=0.0,
        )

    if trigger_row is None:
        return RecoveryOption(strategy="SWAP", label="Aircraft Swap", feasible=False,
                              description="Replace delayed aircraft with ground spare.",
                              infeasibility_reason="Trigger flight not found in schedule.")

    action_log = [
        f"Trigger: {trigger_id} delayed +{result.trigger_delay_min:.0f} min",
        f"Spare pool at DOH: {SPARE_AIRCRAFT_POOL} aircraft available",
        f"Spare readiness time: +{SWAP_READINESS_MINUTES} min from now",
    ]

    # ── Build recovered schedule ─────────────────────────────────────────────
    df_rec = df.copy()

    # Apply trigger delay to inbound (it still lands late — we can't fix that)
    trigger_mask = df_rec["flight_id"] == trigger_id
    if df_rec.loc[trigger_mask, "direction"].values[0] == "inbound":
        df_rec.loc[trigger_mask, "arr_actual"] = (
            df_rec.loc[trigger_mask, "arr_actual"] +
            pd.to_timedelta(result.trigger_delay_min, unit="m")
        )
        df_rec.loc[trigger_mask, "arr_delay_min"] += result.trigger_delay_min
    df_rec.loc[trigger_mask, "status"] = "trigger"

    # Find the ROTATION successors (outbound flights on the same aircraft)
    rotation_successors = [
        v for u, v, d in G.edges(data=True)
        if u == trigger_id and d.get("edge_type") == "ROTATION"
    ]

    residual_delay_min = 0.0
    residual_pax       = 0

    for out_id in rotation_successors:
        out_mask = df_rec["flight_id"] == out_id
        if not out_mask.any():
            continue
        out_row  = df_rec[out_mask].iloc[0]
        dep_sched = out_row["dep_scheduled"]

        # With swap: outbound departs at scheduled time OR spare_ready_time,
        # whichever is later. Spare ready = now + SWAP_READINESS_MINUTES.
        # We model "now" as the trigger's scheduled arrival + trigger delay.
        if pd.notna(trigger_row["arr_scheduled"]):
            swap_ready = (
                trigger_row["arr_scheduled"] +
                pd.to_timedelta(result.trigger_delay_min + SWAP_READINESS_MINUTES, unit="m")
            )
        else:
            swap_ready = dep_sched

        new_dep = max(dep_sched, swap_ready)
        residual_min = (new_dep - dep_sched).total_seconds() / 60

        df_rec.loc[out_mask, "dep_actual"]    = new_dep
        df_rec.loc[out_mask, "dep_delay_min"] = residual_min

        if residual_min > 0:
            df_rec.loc[out_mask, "status"] = "delayed"
            residual_delay_min += residual_min
            residual_pax        = max(residual_pax, int(out_row["pax"]))
            action_log.append(
                f"  {out_id}: departs {new_dep.strftime('%H:%M')} "
                f"(+{residual_min:.0f} min residual via spare)"
            )
        else:
            df_rec.loc[out_mask, "status"] = "recovered"
            action_log.append(f"  {out_id}: departs on time via spare ✓")

    # PAX_CNXN events survive — apply their delays
    pax_cnxn_events = [e for e in result.events if e.edge_type == "PAX_CNXN"]
    for event in pax_cnxn_events:
        mask = df_rec["flight_id"] == event.flight_id
        if not mask.any():
            continue
        df_rec.loc[mask, "dep_actual"] = (
            df_rec.loc[mask, "dep_actual"] +
            pd.to_timedelta(event.delay_min, unit="m")
        )
        df_rec.loc[mask, "dep_delay_min"] += event.delay_min
        df_rec.loc[mask, "status"] = "delayed"
        residual_delay_min += event.delay_min
        action_log.append(f"  {event.flight_id}: {event.pax_stranded} pax stranded (connection missed — swap cannot fix)")

    # ── Cost calculation ─────────────────────────────────────────────────────
    direct_cost      = SWAP_POSITIONING_COST
    residual_cascade_cost = (
        residual_delay_min * COST_AIRCRAFT_PER_MIN +
        residual_delay_min * residual_pax * COST_PAX_PER_MIN
    )
    total_cost       = direct_cost + residual_cascade_cost
    baseline_cost    = result.total_cost_usd
    cost_saved       = baseline_cost - total_cost

    delay_reduction  = result.total_delay_min - residual_delay_min
    delay_pct        = (delay_reduction / result.total_delay_min * 100) if result.total_delay_min > 0 else 0

    pax_saved        = max(0, result.total_pax_affected - residual_pax)

    # Score: weighted combo of delay reduction % and cost efficiency
    # Score: 60% weight on delay reduction, 40% weight on cost efficiency (clamped 0-100)
    cost_ratio = min(1.0, max(0.0, 1.0 - (total_cost / max(baseline_cost, 1))))
    score = max(0, min(100, delay_pct * 0.6 + cost_ratio * 40))

    action_log.append(f"Direct cost: ${direct_cost:,.0f} (spare activation)")
    action_log.append(f"Delay reduced by {delay_reduction:.0f} min ({delay_pct:.0f}%)")
    action_log.append(f"Net cost vs no-action: ${total_cost:,.0f} vs ${baseline_cost:,.0f}")

    return RecoveryOption(
        strategy="SWAP",
        label="Aircraft Swap",
        description=f"Substitute ground spare for {trigger_row.get('aircraft_reg','—')}. "
                    f"Eliminates rotation cascade. Ready in {SWAP_READINESS_MINUTES} min.",
        feasible=True,
        baseline_delay_min=result.total_delay_min,
        recovered_delay_min=residual_delay_min,
        delay_reduction_min=delay_reduction,
        delay_reduction_pct=round(delay_pct, 1),
        baseline_pax_affected=result.total_pax_affected,
        recovered_pax_affected=residual_pax,
        pax_saved=pax_saved,
        pax_stranded=sum(e.pax_stranded for e in pax_cnxn_events),
        direct_cost_usd=round(direct_cost, 0),
        cascade_cost_saved=round(cost_saved, 0),
        net_cost_usd=round(total_cost, 0),
        score=round(score, 1),
        df_recovered=df_rec,
        action_log=action_log,
        residual_events=[e for e in result.events if e.edge_type == "PAX_CNXN"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic 2: DELAY (Compress turnaround)
# Accept the cascade but compress turnarounds to minimum to absorb delay.
# ─────────────────────────────────────────────────────────────────────────────

def heuristic_delay(
    G: nx.DiGraph,
    df: pd.DataFrame,
    result: CascadeResult,
) -> RecoveryOption:
    """
    DELAY: Compress all affected turnarounds to COMPRESS_TURNAROUND_MINUTES.

    Logic:
    1. For each ROTATION-affected outbound, try to shorten turnaround
       from MIN_TURNAROUND (45 min) to COMPRESS_TURNAROUND (38 min).
    2. This absorbs 7 minutes per rotation — partial relief.
    3. No fixed cost (ops pushes harder, no new assets).
    4. All cascade delay still exists but is partially absorbed.

    This is the "absorb and accept" strategy — lowest cost, highest residual delay.
    """
    trigger_id = result.trigger_flight
    action_log = [
        f"Trigger: {trigger_id} delayed +{result.trigger_delay_min:.0f} min",
        f"Strategy: compress all affected turnarounds to {COMPRESS_TURNAROUND_MINUTES} min",
        f"Buffer recovered per rotation: {MIN_TURNAROUND_MINUTES - COMPRESS_TURNAROUND_MINUTES} min",
    ]

    df_rec = df.copy()

    # Apply trigger delay first
    trigger_mask = df_rec["flight_id"] == trigger_id
    if df_rec.loc[trigger_mask, "direction"].values[0] == "inbound":
        df_rec.loc[trigger_mask, "arr_actual"] = (
            df_rec.loc[trigger_mask, "arr_actual"] +
            pd.to_timedelta(result.trigger_delay_min, unit="m")
        )
        df_rec.loc[trigger_mask, "arr_delay_min"] += result.trigger_delay_min
    df_rec.loc[trigger_mask, "status"] = "trigger"

    # Compression savings per ROTATION edge
    turnaround_saving = MIN_TURNAROUND_MINUTES - COMPRESS_TURNAROUND_MINUTES  # 7 min

    total_residual_delay = 0.0
    total_residual_pax   = 0

    for event in result.events:
        mask = df_rec["flight_id"] == event.flight_id
        if not mask.any():
            continue

        if event.edge_type == "ROTATION":
            # Apply compressed delay: original propagated delay - turnaround saving
            compressed_delay = max(0.0, event.delay_min - turnaround_saving)
            df_rec.loc[mask, "dep_actual"] = (
                df_rec.loc[mask, "dep_actual"] +
                pd.to_timedelta(compressed_delay, unit="m")
            )
            df_rec.loc[mask, "dep_delay_min"] = compressed_delay

            severity = "delayed" if compressed_delay >= 15 else "delayed"
            df_rec.loc[mask, "status"] = severity

            total_residual_delay += compressed_delay
            pax = df_rec.loc[mask, "pax"].values[0]
            total_residual_pax = max(total_residual_pax, int(pax))

            action_log.append(
                f"  {event.flight_id}: {event.delay_min:.0f}m → {compressed_delay:.0f}m "
                f"(-{turnaround_saving}m compression applied)"
            )

        elif event.edge_type == "PAX_CNXN":
            df_rec.loc[mask, "dep_actual"] = (
                df_rec.loc[mask, "dep_actual"] +
                pd.to_timedelta(event.delay_min, unit="m")
            )
            df_rec.loc[mask, "dep_delay_min"] += event.delay_min
            df_rec.loc[mask, "status"] = "delayed"
            total_residual_delay += event.delay_min
            action_log.append(
                f"  {event.flight_id}: pax connection delay unchanged (+{event.delay_min:.0f}m)"
            )

    # ── Cost ──────────────────────────────────────────────────────────────────
    direct_cost   = 0.0   # No asset cost — purely operational pressure
    residual_cost = (
        total_residual_delay * COST_AIRCRAFT_PER_MIN +
        total_residual_delay * total_residual_pax * COST_PAX_PER_MIN
    )
    total_cost    = direct_cost + residual_cost
    baseline_cost = result.total_cost_usd
    cost_saved    = baseline_cost - total_cost

    delay_reduction = result.total_delay_min - total_residual_delay
    delay_pct       = (delay_reduction / result.total_delay_min * 100) if result.total_delay_min > 0 else 0
    pax_saved       = max(0, result.total_pax_affected - total_residual_pax)

    # Score: good for cost, poor for delay reduction
    # Score: 50% delay, 50% cost efficiency
    cost_ratio = min(1.0, max(0.0, 1.0 - (total_cost / max(baseline_cost, 1))))
    score = max(0, min(100, delay_pct * 0.5 + cost_ratio * 50))

    action_log.append(f"Zero direct asset cost")
    action_log.append(f"Residual cascade cost: ${residual_cost:,.0f}")
    action_log.append(f"Delay reduced by {delay_reduction:.0f} min ({delay_pct:.0f}%) via compression")

    return RecoveryOption(
        strategy="DELAY",
        label="Compress & Absorb",
        description=(
            f"Compress all affected turnarounds to {COMPRESS_TURNAROUND_MINUTES} min. "
            f"Absorbs {turnaround_saving} min per rotation. No new assets required."
        ),
        feasible=True,
        baseline_delay_min=result.total_delay_min,
        recovered_delay_min=total_residual_delay,
        delay_reduction_min=delay_reduction,
        delay_reduction_pct=round(delay_pct, 1),
        baseline_pax_affected=result.total_pax_affected,
        recovered_pax_affected=total_residual_pax,
        pax_saved=pax_saved,
        pax_stranded=sum(e.pax_stranded for e in result.events if e.edge_type == "PAX_CNXN"),
        direct_cost_usd=0.0,
        cascade_cost_saved=round(cost_saved, 0),
        net_cost_usd=round(total_cost, 0),
        score=round(score, 1),
        df_recovered=df_rec,
        action_log=action_log,
        residual_events=result.events,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic 3: CANCEL
# Cancel the highest-delay outbound. Rebook its passengers. Breaks cascade chain.
# ─────────────────────────────────────────────────────────────────────────────

def heuristic_cancel(
    G: nx.DiGraph,
    df: pd.DataFrame,
    result: CascadeResult,
) -> RecoveryOption:
    """
    CANCEL: Cancel the most cascade-affected outbound flight.

    Logic:
    1. Find the ROTATION successor with the highest propagated delay.
    2. Cancel it. This frees the aircraft from the cascade chain.
    3. Rebook all passengers to next available same-route departure.
    4. Cost = rebooking cost per pax + EU261 compensation if delay > 3h.
    5. Downstream flights in that aircraft's chain are now freed.

    This is the high-immediate-cost, low-residual-delay strategy.
    Best when the cascade is deep and the cancelled flight has low load.
    """
    trigger_id = result.trigger_flight

    # ── Find best candidate to cancel ────────────────────────────────────────
    rotation_events = [e for e in result.events if e.edge_type == "ROTATION"]

    if not rotation_events:
        return RecoveryOption(
            strategy="CANCEL", label="Cancel Flight", feasible=False,
            description="Cancel highest-delay outbound. Rebook passengers.",
            infeasibility_reason="No ROTATION cascade events — nothing to cancel.",
            baseline_delay_min=result.total_delay_min,
            baseline_pax_affected=result.total_pax_affected,
        )

    # Cancel the flight with highest delay (worst rotation hit)
    target_event = max(rotation_events, key=lambda e: e.delay_min)
    target_id    = target_event.flight_id
    target_row   = _flight_row(df, target_id)

    if target_row is None:
        return RecoveryOption(strategy="CANCEL", label="Cancel Flight", feasible=False,
                              description="Cancel highest-delay outbound. Rebook passengers.",
                              infeasibility_reason=f"Flight {target_id} not found.")

    action_log = [
        f"Trigger: {trigger_id} delayed +{result.trigger_delay_min:.0f} min",
        f"Cancel candidate: {target_id} (would be +{target_event.delay_min:.0f} min late)",
        f"Passengers to rebook: {target_row['pax']:,}",
    ]

    # ── Build recovered schedule ─────────────────────────────────────────────
    df_rec = df.copy()

    # Apply trigger delay to inbound
    trigger_mask = df_rec["flight_id"] == trigger_id
    if df_rec.loc[trigger_mask, "direction"].values[0] == "inbound":
        df_rec.loc[trigger_mask, "arr_actual"] = (
            df_rec.loc[trigger_mask, "arr_actual"] +
            pd.to_timedelta(result.trigger_delay_min, unit="m")
        )
        df_rec.loc[trigger_mask, "arr_delay_min"] += result.trigger_delay_min
    df_rec.loc[trigger_mask, "status"] = "trigger"

    # Cancel the target flight
    cancel_mask = df_rec["flight_id"] == target_id
    df_rec.loc[cancel_mask, "status"]       = "cancelled"
    df_rec.loc[cancel_mask, "dep_delay_min"] = 0.0
    action_log.append(f"  {target_id} → CANCELLED")

    # Other cascade events still propagate (non-cancelled chain)
    residual_delay_min = 0.0
    residual_pax       = 0

    for event in result.events:
        if event.flight_id == target_id:
            continue   # cancelled — no delay

        mask = df_rec["flight_id"] == event.flight_id
        if not mask.any():
            continue

        df_rec.loc[mask, "dep_actual"] = (
            df_rec.loc[mask, "dep_actual"] +
            pd.to_timedelta(event.delay_min, unit="m")
        )
        df_rec.loc[mask, "dep_delay_min"] += event.delay_min

        sev = "critical" if event.delay_min >= 120 else "delayed_high" if event.delay_min >= 60 else "delayed"
        df_rec.loc[mask, "status"] = sev

        residual_delay_min += event.delay_min
        pax = df_rec.loc[mask, "pax"].values[0]
        residual_pax = max(residual_pax, int(pax))
        action_log.append(f"  {event.flight_id}: +{event.delay_min:.0f}m residual (not in cancelled chain)")

    # ── Cost ──────────────────────────────────────────────────────────────────
    cancelled_pax = int(target_row["pax"])
    rebooking_cost = cancelled_pax * CANCEL_REBOOKING_COST_PER_PAX

    # EU261 applies if delay on the rebooked service > 3 hours
    eu261_cost = 0.0
    if target_event.delay_min >= CANCEL_EU261_THRESHOLD_MIN:
        eu261_cost = cancelled_pax * CANCEL_EU261_COST_PER_PAX
        action_log.append(
            f"  EU261 compensation triggered (+{target_event.delay_min:.0f}m > {CANCEL_EU261_THRESHOLD_MIN}m): "
            f"${eu261_cost:,.0f}"
        )
    else:
        action_log.append(f"  EU261 NOT triggered ({target_event.delay_min:.0f}m < {CANCEL_EU261_THRESHOLD_MIN}m)")

    direct_cost   = rebooking_cost + eu261_cost
    residual_cost = (
        residual_delay_min * COST_AIRCRAFT_PER_MIN +
        residual_delay_min * residual_pax * COST_PAX_PER_MIN
    )
    total_cost    = direct_cost + residual_cost
    baseline_cost = result.total_cost_usd
    cost_saved    = baseline_cost - total_cost

    delay_reduction = result.total_delay_min - residual_delay_min
    delay_pct       = (delay_reduction / result.total_delay_min * 100) if result.total_delay_min > 0 else 0
    pax_saved       = max(0, result.total_pax_affected - residual_pax)

    # Score: 55% delay, 45% cost efficiency
    cost_ratio = min(1.0, max(0.0, 1.0 - (total_cost / max(baseline_cost, 1))))
    score = max(0, min(100, delay_pct * 0.55 + cost_ratio * 45))

    action_log.append(f"Rebooking cost: ${rebooking_cost:,.0f} ({cancelled_pax} pax × ${CANCEL_REBOOKING_COST_PER_PAX})")
    action_log.append(f"Total direct cost: ${direct_cost:,.0f}")
    action_log.append(f"Delay reduced by {delay_reduction:.0f} min ({delay_pct:.0f}%)")

    return RecoveryOption(
        strategy="CANCEL",
        label="Cancel & Rebook",
        description=(
            f"Cancel {target_id} (+{target_event.delay_min:.0f}m delayed). "
            f"Rebook {cancelled_pax:,} pax. Breaks cascade chain."
        ),
        feasible=True,
        baseline_delay_min=result.total_delay_min,
        recovered_delay_min=residual_delay_min,
        delay_reduction_min=delay_reduction,
        delay_reduction_pct=round(delay_pct, 1),
        baseline_pax_affected=result.total_pax_affected,
        recovered_pax_affected=residual_pax,
        pax_saved=pax_saved,
        pax_stranded=cancelled_pax,
        direct_cost_usd=round(direct_cost, 0),
        cascade_cost_saved=round(cost_saved, 0),
        net_cost_usd=round(total_cost, 0),
        score=round(score, 1),
        df_recovered=df_rec,
        action_log=action_log,
        residual_events=[e for e in result.events if e.flight_id != target_id],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Master runner
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_all_recovery_options(
    G: nx.DiGraph,
    df: pd.DataFrame,
    result: CascadeResult,
) -> list:
    """
    Run all three heuristics and return sorted list of RecoveryOption.
    Sorted by score descending (best option first).
    """
    options = [
        heuristic_swap(G, df, result),
        heuristic_delay(G, df, result),
        heuristic_cancel(G, df, result),
    ]
    return sorted(options, key=lambda o: o.score, reverse=True)
