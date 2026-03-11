"""
session_state.py
----------------
Helpers for serializing callback state into stable Dash store payloads.
"""

from __future__ import annotations

import json
from types import SimpleNamespace


def event_direction(graph, flight_id: str) -> str:
    """Return a flight direction for report/export payloads."""
    if flight_id in graph.nodes:
        return graph.nodes[flight_id].get("direction", "outbound")
    return "outbound"


def serialize_cascade_result(result, graph) -> str:
    """Persist the current cascade result as JSON for export/reuse."""
    payload = result.summary()
    payload["events"] = [
        {
            "flight_id": event.flight_id,
            "direction": event_direction(graph, event.flight_id),
            "edge_type": event.edge_type,
            "delay_min": event.delay_min,
            "pax_affected": event.pax_affected,
            "pax_stranded": event.pax_stranded,
            "cost_usd": event.cost_usd,
            "severity": event.severity,
            "caused_by": event.caused_by,
            "propagation_path": event.propagation_path,
        }
        for event in result.events
    ]
    return json.dumps(payload)


def deserialize_cascade_store(cascade_store: str | None) -> dict | None:
    """Read back the stored cascade payload, if any."""
    if not cascade_store:
        return None
    try:
        payload = json.loads(cascade_store)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def serialize_recovery_options(options) -> str:
    """Reduce recovery options to a stable, exportable JSON payload."""
    payload = [
        {
            "strategy": option.strategy,
            "label": option.label,
            "feasible": option.feasible,
            "delay_reduction_min": option.delay_reduction_min,
            "delay_reduction_pct": option.delay_reduction_pct,
            "direct_cost_usd": option.direct_cost_usd,
            "net_cost_usd": option.net_cost_usd,
            "pax_saved": option.pax_saved,
            "score": option.score,
            "pareto_efficient": option.pareto_efficient,
            "recommendation": option.recommendation,
            "objective_score": getattr(option, "objective_score", None),
        }
        for option in options
    ]
    return json.dumps(payload)


def deserialize_recovery_store(recovery_store: str | None) -> list[dict]:
    """Read back export-ready recovery option payloads."""
    if not recovery_store:
        return []
    try:
        payload = json.loads(recovery_store)
    except (TypeError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def deserialize_mc_store(mc_store: str | None):
    """Rebuild a minimal MonteCarloResult-like object from stored JSON."""
    if not mc_store:
        return None

    try:
        payload = json.loads(mc_store)
    except (TypeError, json.JSONDecodeError):
        return None

    risk_profiles = {}
    for fid, profile in payload.get("risk_profiles", {}).items():
        risk_profiles[fid] = SimpleNamespace(**({"trigger_avg_cascade": 0.0, **profile}))

    summary = SimpleNamespace(
        n_scenarios=payload.get("n_scenarios", 0),
        mean_flights_affected=payload.get("mean_flights_affected", 0.0),
        p50_flights_affected=payload.get("p50_flights_affected", 0.0),
        p90_flights_affected=payload.get("p90_flights_affected", 0.0),
        p99_flights_affected=payload.get("p99_flights_affected", 0.0),
        mean_cost_usd=payload.get("mean_cost_usd", 0.0),
        p50_cost_usd=payload.get("p50_cost_usd", 0.0),
        p90_cost_usd=payload.get("p90_cost_usd", 0.0),
        p99_cost_usd=payload.get("p99_cost_usd", 0.0),
        mean_total_delay=payload.get("mean_total_delay", 0.0),
        p90_total_delay=payload.get("p90_total_delay", 0.0),
        zero_cascade_pct=payload.get("zero_cascade_pct", 0.0),
        critical_scenario_pct=payload.get("critical_scenario_pct", 0.0),
        top_triggers=payload.get("top_triggers", []),
    )

    return SimpleNamespace(
        scenarios=[None] * int(payload.get("n_scenarios", 0)),
        risk_profiles=risk_profiles,
        network_summary=summary,
        delay_samples=[],
        cost_samples=[],
        n_scenarios=int(payload.get("n_scenarios", 0)),
    )

