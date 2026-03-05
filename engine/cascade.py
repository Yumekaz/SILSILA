"""
cascade.py
----------
Core cascade propagation algorithm.

Given:
  - A flight dependency graph G (NetworkX DiGraph)
  - A trigger flight ID
  - An initial delay in minutes

Produces:
  - Ordered list of all affected downstream flights
  - For each: delay amount, propagation path, edge type that caused it
  - Aggregate metrics: total delay-minutes, pax affected, estimated cost

Algorithm: Modified BFS on the dependency graph.
  For each edge type, delay propagates differently:
    ROTATION : delay = max(0, trigger_delay - turnaround_slack)
    CREW     : delay = max(0, trigger_delay - crew_slack) * 0.7 (crew have some flexibility)
    PAX_CNXN : binary — if delay > buffer, flight is marked as "pax-impacted" (flight itself may hold or depart)
"""

import networkx as nx
import pandas as pd
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from engine.config import COST_PAX_PER_MIN, COST_AIRCRAFT_PER_MIN


@dataclass
class CascadeEvent:
    """Single affected flight in a cascade chain."""
    flight_id:       str
    delay_min:       float
    edge_type:       str           # ROTATION / CREW / PAX_CNXN
    caused_by:       str           # flight_id of the upstream flight
    propagation_path: list         # ordered chain from trigger to this flight
    pax_affected:    int = 0
    pax_stranded:    int = 0       # pax who miss connection (PAX_CNXN only)
    cost_usd:        float = 0.0
    severity:        str = "LOW"   # LOW / MEDIUM / HIGH / CRITICAL

    def severity_label(self) -> str:
        if self.delay_min >= 120:  return "CRITICAL"
        if self.delay_min >= 60:   return "HIGH"
        if self.delay_min >= 30:   return "MEDIUM"
        return "LOW"


@dataclass
class CascadeResult:
    """Full output of one cascade simulation run."""
    trigger_flight:    str
    trigger_delay_min: float
    events:            list = field(default_factory=list)  # list[CascadeEvent]
    total_delay_min:   float = 0.0
    total_pax_affected: int  = 0
    total_pax_stranded: int  = 0
    total_cost_usd:    float = 0.0
    max_depth:         int   = 0
    simulation_time:   Optional[datetime] = None

    @property
    def flights_affected(self) -> int:
        return len(self.events)

    def summary(self) -> dict:
        return {
            "trigger":             self.trigger_flight,
            "trigger_delay_min":   self.trigger_delay_min,
            "flights_affected":    self.flights_affected,
            "total_delay_min":     round(self.total_delay_min, 1),
            "total_pax_affected":  self.total_pax_affected,
            "total_pax_stranded":  self.total_pax_stranded,
            "estimated_cost_usd":  round(self.total_cost_usd, 0),
            "cascade_depth":       self.max_depth,
            "critical_count":      sum(1 for e in self.events if e.delay_min >= 120),
            "high_count":          sum(1 for e in self.events if 60 <= e.delay_min < 120),
            "medium_count":        sum(1 for e in self.events if 30 <= e.delay_min < 60),
        }


def _propagated_delay(upstream_delay: float, edge_data: dict) -> tuple[float, int]:
    """
    Calculate how much delay propagates through a single edge.

    Returns: (delay_minutes_propagated, stranded_pax)
    """
    edge_type  = edge_data.get("edge_type", "ROTATION")
    slack_min  = float(edge_data.get("slack_min", 0))

    if edge_type == "ROTATION":
        # Aircraft physically can't leave until MIN_TURNAROUND after it lands.
        # Delay eats into the slack. Once slack is consumed, delay propagates 1:1.
        propagated = max(0.0, upstream_delay - slack_min)
        return propagated, 0

    elif edge_type == "CREW":
        # Crew have some scheduling flexibility (operations can sometimes extend duty).
        # Model as 70% propagation efficiency after the slack is consumed.
        raw_prop = max(0.0, upstream_delay - slack_min)
        propagated = raw_prop * 0.70
        return propagated, 0

    elif edge_type == "PAX_CNXN":
        # If delay > connection buffer, passengers miss connection.
        # The downstream flight itself is NOT delayed (it won't hold indefinitely),
        # but the stranded pax count increases.
        cnxn_buffer = float(edge_data.get("slack_min", 45))
        connecting_pax = int(edge_data.get("connecting_pax", 0))

        if upstream_delay > cnxn_buffer:
            # Pax miss their connection — downstream flight gets a small operational
            # hold if pax count is significant (airlines sometimes hold short for high-value pax)
            hold_delay = 5.0 if connecting_pax > 20 else 0.0
            return hold_delay, connecting_pax
        return 0.0, 0

    return 0.0, 0


def run_cascade(
    G: nx.DiGraph,
    trigger_flight_id: str,
    trigger_delay_min: float,
    max_depth: int = 8
) -> CascadeResult:
    """
    Run BFS cascade propagation from trigger flight.

    Parameters
    ----------
    G                 : The dependency graph (will not be mutated)
    trigger_flight_id : The flight that is delayed (e.g. 'QR007')
    trigger_delay_min : How many minutes late (e.g. 90.0)
    max_depth         : Safety limit on propagation depth

    Returns
    -------
    CascadeResult with all affected flights and metrics
    """
    if trigger_flight_id not in G:
        raise ValueError(f"Flight {trigger_flight_id} not found in graph.")
    if trigger_delay_min <= 0:
        return CascadeResult(
            trigger_flight=trigger_flight_id,
            trigger_delay_min=trigger_delay_min,
            simulation_time=datetime.utcnow()
        )

    result = CascadeResult(
        trigger_flight=trigger_flight_id,
        trigger_delay_min=trigger_delay_min,
        simulation_time=datetime.utcnow()
    )

    # BFS queue: (flight_id, delay_minutes, depth, path_so_far)
    queue   = deque([(trigger_flight_id, trigger_delay_min, 0, [trigger_flight_id])])
    visited = {}  # flight_id → max delay seen (so we always keep worst case)

    visited[trigger_flight_id] = trigger_delay_min

    while queue:
        current_id, current_delay, depth, path = queue.popleft()

        if depth >= max_depth or current_delay < 1.0:
            continue

        for neighbor_id in G.successors(current_id):
            edge_data = G.edges[current_id, neighbor_id]
            propagated_delay, stranded_pax = _propagated_delay(current_delay, edge_data)

            # Only process if this route produces a meaningful delay
            if propagated_delay < 1.0 and stranded_pax == 0:
                continue

            # If we've seen this node before, only re-process if delay is worse
            if neighbor_id in visited and visited[neighbor_id] >= propagated_delay:
                continue

            visited[neighbor_id] = propagated_delay

            node_data = G.nodes[neighbor_id]
            pax       = node_data.get("pax", 0)

            # Cost calculation
            cost = (
                propagated_delay * COST_AIRCRAFT_PER_MIN +
                propagated_delay * pax * COST_PAX_PER_MIN
            )

            event = CascadeEvent(
                flight_id=neighbor_id,
                delay_min=round(propagated_delay, 1),
                edge_type=edge_data.get("edge_type", "ROTATION"),
                caused_by=current_id,
                propagation_path=path + [neighbor_id],
                pax_affected=pax,
                pax_stranded=stranded_pax,
                cost_usd=round(cost, 2),
            )
            event.severity = event.severity_label()

            result.events.append(event)
            result.total_delay_min   += propagated_delay
            result.total_pax_affected = max(result.total_pax_affected, pax)
            result.total_pax_stranded += stranded_pax
            result.total_cost_usd    += cost
            result.max_depth          = max(result.max_depth, depth + 1)

            new_path = path + [neighbor_id]
            queue.append((neighbor_id, propagated_delay, depth + 1, new_path))

    # Sort events by delay (worst first)
    result.events.sort(key=lambda e: e.delay_min, reverse=True)

    logger.info(
        "Cascade from %s (+%d min): %d flights affected, "
        "total delay %.0f min, estimated cost $%.0f",
        trigger_flight_id, trigger_delay_min,
        result.flights_affected, result.total_delay_min, result.total_cost_usd
    )

    return result


def cascaded_schedule(
    df_original,
    G: nx.DiGraph,
    result: CascadeResult
):
    """
    Apply cascade delays to the schedule DataFrame and return the updated version.
    Used for Gantt chart rendering.
    """
    df = df_original.copy()

    # Apply trigger delay
    trigger_mask = df["flight_id"] == result.trigger_flight
    if df.loc[trigger_mask, "direction"].values[0] == "inbound":
        df.loc[trigger_mask, "arr_actual"] = (
            df.loc[trigger_mask, "arr_actual"] +
            pd.to_timedelta(result.trigger_delay_min, unit="m")
        )
        df.loc[trigger_mask, "arr_delay_min"] += result.trigger_delay_min
    else:
        df.loc[trigger_mask, "dep_actual"] = (
            df.loc[trigger_mask, "dep_actual"] +
            pd.to_timedelta(result.trigger_delay_min, unit="m")
        )
        df.loc[trigger_mask, "dep_delay_min"] += result.trigger_delay_min
    df.loc[trigger_mask, "status"] = "trigger"

    # Apply cascaded delays
    for event in result.events:
        mask = df["flight_id"] == event.flight_id
        if not mask.any():
            continue

        direction = df.loc[mask, "direction"].values[0]
        if direction == "inbound":
            df.loc[mask, "arr_actual"] = (
                df.loc[mask, "arr_actual"] +
                pd.to_timedelta(event.delay_min, unit="m")
            )
            df.loc[mask, "arr_delay_min"] += event.delay_min
        else:
            df.loc[mask, "dep_actual"] = (
                df.loc[mask, "dep_actual"] +
                pd.to_timedelta(event.delay_min, unit="m")
            )
            df.loc[mask, "dep_delay_min"] += event.delay_min

        severity = event.severity
        if severity == "CRITICAL":
            df.loc[mask, "status"] = "critical"
        elif severity == "HIGH":
            df.loc[mask, "status"] = "delayed_high"
        else:
            df.loc[mask, "status"] = "delayed"

    return df
