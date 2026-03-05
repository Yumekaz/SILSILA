"""
sensitivity.py
--------------
Turnaround sensitivity analysis for the cascade model.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from engine.cascade import run_cascade
from engine.graph_builder import build_graph_with_constraints


@dataclass
class SensitivityPoint:
    min_turnaround_min: float
    mean_flights_affected: float
    mean_total_delay_min: float
    mean_cost_usd: float
    critical_scenarios: int
    scenario_count: int


def run_turnaround_sensitivity(
    df: pd.DataFrame,
    trigger_ids: list[str] | None = None,
    trigger_delay_min: float = 60.0,
    min_turnaround_values: list[float] | None = None,
) -> list[SensitivityPoint]:
    """
    Compare cascade severity as the minimum turnaround requirement changes.

    This is a deterministic sensitivity sweep over one or more trigger flights.
    """
    if min_turnaround_values is None:
        min_turnaround_values = [35.0, 45.0, 55.0, 65.0]

    if trigger_ids is None:
        trigger_ids = list(df.loc[df["direction"] == "inbound", "flight_id"])

    if not trigger_ids:
        raise ValueError("At least one inbound trigger flight is required.")

    results: list[SensitivityPoint] = []
    for turnaround in min_turnaround_values:
        graph = build_graph_with_constraints(df, min_turnaround_minutes=turnaround)
        flights_affected = []
        delay_minutes = []
        total_costs = []
        critical_count = 0

        for trigger_id in trigger_ids:
            cascade = run_cascade(graph, trigger_id, trigger_delay_min)
            flights_affected.append(cascade.flights_affected)
            delay_minutes.append(cascade.total_delay_min)
            total_costs.append(cascade.total_cost_usd)
            if any(event.severity == "CRITICAL" for event in cascade.events):
                critical_count += 1

        scenario_count = len(trigger_ids)
        results.append(SensitivityPoint(
            min_turnaround_min=float(turnaround),
            mean_flights_affected=sum(flights_affected) / scenario_count,
            mean_total_delay_min=sum(delay_minutes) / scenario_count,
            mean_cost_usd=sum(total_costs) / scenario_count,
            critical_scenarios=critical_count,
            scenario_count=scenario_count,
        ))

    return results
