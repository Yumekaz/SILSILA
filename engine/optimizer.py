"""
optimizer.py
------------
Discrete optimization layer over feasible recovery candidates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OptimizationCandidate:
    strategy: str
    label: str
    objective_score: float
    net_cost_usd: float
    recovered_delay_min: float
    pax_stranded: int
    pareto_efficient: bool


@dataclass
class OptimizationResult:
    best_strategy: str | None
    best_label: str | None
    objective_weights: dict[str, float]
    frontier_labels: list[str]
    candidates: list[OptimizationCandidate]


DEFAULT_OBJECTIVE_WEIGHTS = {
    "net_cost": 0.45,
    "residual_delay": 0.40,
    "pax_stranded": 0.15,
}


def optimize_recovery_options(options, weights: dict[str, float] | None = None) -> OptimizationResult:
    """
    Solve a discrete recovery-selection problem across available feasible candidates.

    Objective:
    minimize weighted normalized net cost, residual delay, and stranded passengers.
    """
    weights = weights or DEFAULT_OBJECTIVE_WEIGHTS.copy()
    feasible = [option for option in options if option.feasible]
    if not feasible:
        return OptimizationResult(
            best_strategy=None,
            best_label=None,
            objective_weights=weights,
            frontier_labels=[],
            candidates=[],
        )

    max_cost = max(max(option.net_cost_usd, 0.0) for option in feasible) or 1.0
    max_delay = max(option.recovered_delay_min for option in feasible) or 1.0
    max_stranded = max(option.pax_stranded for option in feasible) or 1.0

    candidates: list[OptimizationCandidate] = []
    for option in feasible:
        normalized_cost = max(option.net_cost_usd, 0.0) / max_cost
        normalized_delay = option.recovered_delay_min / max_delay
        normalized_stranded = option.pax_stranded / max_stranded
        objective_score = (
            weights["net_cost"] * normalized_cost +
            weights["residual_delay"] * normalized_delay +
            weights["pax_stranded"] * normalized_stranded
        )
        candidates.append(OptimizationCandidate(
            strategy=option.strategy,
            label=option.label,
            objective_score=round(objective_score, 4),
            net_cost_usd=option.net_cost_usd,
            recovered_delay_min=option.recovered_delay_min,
            pax_stranded=option.pax_stranded,
            pareto_efficient=option.pareto_efficient,
        ))
        option.objective_score = round(objective_score, 4)

    best = min(candidates, key=lambda candidate: candidate.objective_score)
    frontier_labels = [candidate.label for candidate in candidates if candidate.pareto_efficient]
    return OptimizationResult(
        best_strategy=best.strategy,
        best_label=best.label,
        objective_weights=weights,
        frontier_labels=frontier_labels,
        candidates=sorted(candidates, key=lambda candidate: candidate.objective_score),
    )
