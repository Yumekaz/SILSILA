from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import networkx as nx
import pytest

from engine.cascade import run_cascade
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from engine.recovery import evaluate_all_recovery_options
from ui.analysis_views import build_monte_carlo_outputs, build_sensitivity_outputs
from ui.callbacks_core import COLORS
from ui.session_state import (
    cascade_store_matches_request,
    deserialize_mc_store,
    serialize_cascade_result,
    serialize_mc_result,
    serialize_recovery_options,
)
from ui.workflows import prepare_pdf_export_bundle, run_simulation_bundle, select_recovery_option


@pytest.fixture(scope="module")
def schedule_df():
    return load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)


@pytest.fixture(scope="module")
def dependency_graph(schedule_df):
    return build_graph(schedule_df)


def test_select_recovery_option_rehydrates_dataframe_and_store(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)
    recovery_store = serialize_recovery_options(options)

    selected_idx = next(idx for idx, option in enumerate(options) if option.feasible)
    selection = select_recovery_option(recovery_store, selected_idx)

    assert selection is not None
    assert selection.option_payload["strategy"] == options[selected_idx].strategy
    assert len(selection.recovered_df) == len(schedule_df)
    assert selection.affected_ids == {
        event["flight_id"] for event in selection.option_payload["residual_events"]
    }
    assert json.loads(selection.selected_store)["strategy"] == options[selected_idx].strategy


def test_prepare_pdf_export_bundle_rebuilds_missing_stores(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)
    selected_idx = next(idx for idx, option in enumerate(options) if option.feasible)
    selection = select_recovery_option(serialize_recovery_options(options), selected_idx)

    bundle = prepare_pdf_export_bundle(
        dependency_graph,
        schedule_df,
        trigger_id,
        30.0,
        None,
        None,
        selection.selected_store,
    )

    assert bundle.cascade_payload["trigger"] == trigger_id
    assert len(bundle.recovery_payload) == 3
    assert bundle.selected_strategy == selection.option_payload["strategy"]
    assert any(
        option["strategy"] == bundle.selected_strategy and option["label"].endswith("[SELECTED]")
        for option in bundle.recovery_payload
    )


def test_mc_store_serializer_round_trip_preserves_summary_and_profiles():
    mc = SimpleNamespace(
        network_summary=SimpleNamespace(
            n_scenarios=12,
            mean_flights_affected=2.5,
            p50_flights_affected=2.0,
            p90_flights_affected=5.0,
            p99_flights_affected=7.0,
            mean_cost_usd=1000.0,
            p50_cost_usd=900.0,
            p90_cost_usd=2000.0,
            p99_cost_usd=3000.0,
            mean_total_delay=44.0,
            p90_total_delay=90.0,
            zero_cascade_pct=25.0,
            critical_scenario_pct=8.0,
            top_triggers=[("QR021", 12345.0)],
        ),
        risk_profiles={
            "QR021": SimpleNamespace(
                risk_label="HIGH",
                risk_score=0.42,
                victim_probability=0.33,
                trigger_avg_cascade=4.0,
                trigger_avg_cost=12345.0,
                direction="inbound",
                origin="KJFK",
                destination="OTHH",
                aircraft_type="A350-1000",
            )
        },
    )

    restored = deserialize_mc_store(serialize_mc_result(mc))

    assert restored is not None
    assert restored.network_summary.n_scenarios == 12
    assert restored.network_summary.top_triggers == [["QR021", 12345.0]]
    assert restored.risk_profiles["QR021"].trigger_avg_cascade == 4.0
    assert restored.risk_profiles["QR021"].risk_label == "HIGH"


def test_build_monte_carlo_outputs_returns_charts_and_store():
    graph = nx.DiGraph()
    graph.add_node("QR001")
    graph.add_node("QR002")

    mc = SimpleNamespace(
        network_summary=SimpleNamespace(
            n_scenarios=20,
            runtime_seconds=1.25,
            mean_flights_affected=2.1,
            p50_flights_affected=2.0,
            p90_flights_affected=5.0,
            p99_flights_affected=7.0,
            mean_cost_usd=1000.0,
            p50_cost_usd=900.0,
            p90_cost_usd=2000.0,
            p99_cost_usd=3000.0,
            mean_total_delay=44.0,
            p90_total_delay=90.0,
            zero_cascade_pct=25.0,
            critical_scenario_pct=8.0,
            top_triggers=[("QR001", 8000.0)],
        ),
        risk_profiles={
            "QR001": SimpleNamespace(
                risk_label="HIGH",
                risk_score=0.40,
                victim_probability=0.25,
                trigger_avg_cascade=4.0,
                trigger_avg_cost=8000.0,
                direction="inbound",
                origin="LHR",
                destination="OTHH",
                aircraft_type="A350",
            ),
            "QR002": SimpleNamespace(
                risk_label="MEDIUM",
                risk_score=0.15,
                victim_probability=0.10,
                trigger_avg_cascade=1.0,
                trigger_avg_cost=1000.0,
                direction="outbound",
                origin="OTHH",
                destination="CDG",
                aircraft_type="B787",
            ),
        },
        cost_samples=[500.0, 1000.0, 2000.0],
        delay_samples=[10.0, 20.0, 30.0],
    )

    status, charts, stats, store = build_monte_carlo_outputs(mc, graph, COLORS)

    assert status is not None
    assert stats is not None
    assert len(charts) == 3
    restored = deserialize_mc_store(store)
    assert restored is not None
    assert restored.network_summary.n_scenarios == 20


def test_build_sensitivity_outputs_returns_dual_axis_figure():
    points = [
        SimpleNamespace(min_turnaround_min=35.0, mean_flights_affected=4.0, mean_total_delay_min=180.0),
        SimpleNamespace(min_turnaround_min=45.0, mean_flights_affected=3.0, mean_total_delay_min=140.0),
        SimpleNamespace(min_turnaround_min=55.0, mean_flights_affected=2.0, mean_total_delay_min=110.0),
        SimpleNamespace(min_turnaround_min=65.0, mean_flights_affected=1.5, mean_total_delay_min=90.0),
    ]

    status, figure, summary = build_sensitivity_outputs(points, "QR001", 30.0, COLORS)

    assert status is not None
    assert summary is not None
    assert len(figure.data) == 2
    assert "TURNAROUND SENSITIVITY" in figure.layout.title.text


def test_prepare_pdf_export_bundle_recomputes_stale_scenario_stores(schedule_df, dependency_graph):
    old_bundle = run_simulation_bundle(dependency_graph, schedule_df, "QR007", 30.0)
    stale_cascade_store = serialize_cascade_result(old_bundle.cascade_result, dependency_graph)
    stale_recovery_store = serialize_recovery_options(old_bundle.recovery_options)

    bundle = prepare_pdf_export_bundle(
        dependency_graph,
        schedule_df,
        "QR021",
        60.0,
        stale_cascade_store,
        stale_recovery_store,
        None,
    )

    assert bundle.cascade_payload["trigger"] == "QR021"
    assert bundle.cascade_payload["trigger_delay_min"] == 60.0


def test_cascade_store_match_helper_detects_stale_controls(schedule_df, dependency_graph):
    bundle = run_simulation_bundle(dependency_graph, schedule_df, "QR007", 30.0)
    cascade_store = serialize_cascade_result(bundle.cascade_result, dependency_graph)

    assert cascade_store_matches_request(cascade_store, "QR007", 30.0)
    assert not cascade_store_matches_request(cascade_store, "QR021", 30.0)
    assert not cascade_store_matches_request(cascade_store, "QR007", 60.0)
