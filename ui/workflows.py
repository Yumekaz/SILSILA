"""
workflows.py
------------
Reusable workflow helpers for simulation and recovery orchestration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from engine.cascade import cascaded_schedule, run_cascade
from engine.optimizer import optimize_recovery_options
from engine.recovery import evaluate_all_recovery_options
from ui.session_state import (
    deserialize_cascade_store,
    deserialize_recovery_option_frame,
    deserialize_recovery_store,
    serialize_cascade_result,
    serialize_recovery_options,
)


@dataclass
class SimulationBundle:
    cascade_result: object
    cascaded_df: object
    affected_ids: set[str]
    recovery_options: list
    optimization: object


@dataclass
class RecoverySelection:
    option_payload: dict
    recovered_df: object
    affected_ids: set[str]
    selected_store: str


@dataclass
class PdfExportBundle:
    cascade_payload: dict
    recovery_payload: list[dict]
    selected_strategy: str | None


def run_simulation_bundle(graph, df, flight_id: str, delay_min: float) -> SimulationBundle:
    """Run the core simulation pipeline once and return all derived artifacts."""
    cascade_result = run_cascade(graph, flight_id, float(delay_min))
    cascaded_df = cascaded_schedule(df, graph, cascade_result)
    affected_ids = {event.flight_id for event in cascade_result.events}
    recovery_options = evaluate_all_recovery_options(graph, df, cascade_result)
    optimization = optimize_recovery_options(recovery_options)
    return SimulationBundle(
        cascade_result=cascade_result,
        cascaded_df=cascaded_df,
        affected_ids=affected_ids,
        recovery_options=recovery_options,
        optimization=optimization,
    )


def select_recovery_option(recovery_store: str | None, selected_idx: int) -> RecoverySelection | None:
    """Rebuild a stored recovery option into a callback-ready selection."""
    options = deserialize_recovery_store(recovery_store)
    if selected_idx < 0 or selected_idx >= len(options):
        return None

    selected = options[selected_idx]
    recovered_df = deserialize_recovery_option_frame(selected)
    if not selected.get("feasible") or recovered_df is None:
        return None

    affected_ids = {
        event.get("flight_id")
        for event in selected.get("residual_events", [])
        if event.get("flight_id")
    }
    return RecoverySelection(
        option_payload=selected,
        recovered_df=recovered_df,
        affected_ids=affected_ids,
        selected_store=json.dumps(
            {"strategy": selected.get("strategy"), "label": selected.get("label")}
        ),
    )


def prepare_pdf_export_bundle(
    graph,
    df,
    flight_id: str,
    delay_min: float,
    cascade_store: str | None,
    recovery_store: str | None,
    selected_recovery_store: str | None,
) -> PdfExportBundle:
    """Hydrate the PDF export payloads from stores, recomputing once if needed."""
    selected_strategy = _selected_strategy_from_store(selected_recovery_store)
    cascade_payload = deserialize_cascade_store(cascade_store)
    recovery_payload = deserialize_recovery_store(recovery_store)

    bundle = None
    if cascade_payload is None or not recovery_payload:
        bundle = run_simulation_bundle(graph, df, flight_id, delay_min)

    if cascade_payload is None and bundle is not None:
        cascade_payload = deserialize_cascade_store(
            serialize_cascade_result(bundle.cascade_result, graph)
        )

    if not recovery_payload and bundle is not None:
        recovery_payload = deserialize_recovery_store(
            serialize_recovery_options(bundle.recovery_options)
        )

    prepared_recovery_payload = [dict(option) for option in recovery_payload]
    if selected_strategy:
        for option in prepared_recovery_payload:
            if option.get("strategy") == selected_strategy:
                option["label"] = f"{option['label']} [SELECTED]"
                break

    return PdfExportBundle(
        cascade_payload=cascade_payload or {},
        recovery_payload=prepared_recovery_payload,
        selected_strategy=selected_strategy,
    )


def _selected_strategy_from_store(selected_recovery_store: str | None) -> str | None:
    if not selected_recovery_store:
        return None
    try:
        payload = json.loads(selected_recovery_store)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    strategy = payload.get("strategy")
    return strategy if isinstance(strategy, str) else None
