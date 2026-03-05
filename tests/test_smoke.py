from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from app import build_flight_options
from engine.data_loader import REQUIRED_COLUMNS, load_schedule
from engine.graph_builder import build_graph, graph_summary
from engine.cascade import run_cascade, cascaded_schedule
from engine.recovery import evaluate_all_recovery_options
from engine.monte_carlo import run_monte_carlo, build_heatmap_data
from engine.optimizer import optimize_recovery_options
from engine.pdf_report import generate_pdf_report
from engine.sensitivity import run_turnaround_sensitivity
from engine.validation import validate_graph, validate_schedule
from ui.session_state import (
    deserialize_cascade_store,
    deserialize_mc_store,
    deserialize_recovery_store,
    serialize_cascade_result,
    serialize_recovery_options,
)


@pytest.fixture(scope="module")
def schedule_df():
    return load_schedule(datetime.now(timezone.utc), use_opensky=False)


@pytest.fixture(scope="module")
def dependency_graph(schedule_df):
    return build_graph(schedule_df)


def test_schedule_has_required_schema(schedule_df):
    assert not schedule_df.empty
    assert REQUIRED_COLUMNS.issubset(schedule_df.columns)
    assert (schedule_df["direction"] == "inbound").any()
    assert (schedule_df["direction"] == "outbound").any()
    assert "data_source" in schedule_df.attrs


def test_flight_options_are_inbound_only(schedule_df):
    options = build_flight_options(schedule_df, inbound_only=True)
    option_ids = {option["value"] for option in options}
    outbound_ids = set(schedule_df.loc[schedule_df["direction"] == "outbound", "flight_id"])

    assert options
    assert option_ids.isdisjoint(outbound_ids)


def test_graph_builds_and_has_core_edge_types(dependency_graph):
    summary = graph_summary(dependency_graph)
    assert summary["nodes"] > 0
    assert summary["edges"] > 0
    for edge_type in ("ROTATION", "PAX_CNXN", "CREW"):
        assert summary["edge_types"].get(edge_type, 0) >= 1


def test_schedule_and_graph_validation_reports_pass(schedule_df, dependency_graph):
    schedule_report = validate_schedule(schedule_df)
    graph_report = validate_graph(dependency_graph)

    assert schedule_report.passed
    assert not schedule_report.errors
    assert graph_report.passed
    assert not graph_report.errors


def test_rotation_edges_match_aircraft_and_schedule_slack(schedule_df, dependency_graph):
    rotation_edges = [
        (u, v, data) for u, v, data in dependency_graph.edges(data=True)
        if data.get("edge_type") == "ROTATION"
    ]

    assert rotation_edges
    for u, v, data in rotation_edges:
        inb = schedule_df[schedule_df["flight_id"] == u].iloc[0]
        out = schedule_df[schedule_df["flight_id"] == v].iloc[0]

        assert inb["direction"] == "inbound"
        assert out["direction"] == "outbound"
        assert inb["aircraft_reg"] == out["aircraft_reg"]

        expected_slack = round(
            (out["dep_scheduled"] - inb["arr_actual"]).total_seconds() / 60 - 45,
            1,
        )
        assert data["slack_min"] == pytest.approx(expected_slack)


def test_cascade_pipeline_returns_consistent_outputs(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    cascaded_df = cascaded_schedule(schedule_df, dependency_graph, result)

    assert result.trigger_flight == trigger_id
    assert result.trigger_delay_min == 30.0
    assert len(cascaded_df) == len(schedule_df)
    assert "status" in cascaded_df.columns


def test_cascaded_schedule_updates_correct_time_column(schedule_df, dependency_graph):
    inbound_id = schedule_df[schedule_df["direction"] == "inbound"].iloc[0]["flight_id"]
    outbound_id = schedule_df[schedule_df["direction"] == "outbound"].iloc[0]["flight_id"]

    inbound_result = run_cascade(dependency_graph, inbound_id, 25.0)
    outbound_result = run_cascade(dependency_graph, outbound_id, 40.0)

    inbound_df = cascaded_schedule(schedule_df, dependency_graph, inbound_result)
    outbound_df = cascaded_schedule(schedule_df, dependency_graph, outbound_result)

    inbound_row_before = schedule_df[schedule_df["flight_id"] == inbound_id].iloc[0]
    inbound_row_after = inbound_df[inbound_df["flight_id"] == inbound_id].iloc[0]
    assert inbound_row_after["arr_delay_min"] == pytest.approx(inbound_row_before["arr_delay_min"] + 25.0)
    assert pd.isna(inbound_row_after["dep_actual"])

    outbound_row_before = schedule_df[schedule_df["flight_id"] == outbound_id].iloc[0]
    outbound_row_after = outbound_df[outbound_df["flight_id"] == outbound_id].iloc[0]
    assert outbound_row_after["dep_delay_min"] == pytest.approx(outbound_row_before["dep_delay_min"] + 40.0)
    assert pd.isna(outbound_row_after["arr_actual"])


def test_recovery_options_are_ranked_and_complete(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)

    assert len(options) == 3
    assert all(options[i].score >= options[i + 1].score for i in range(len(options) - 1))
    assert {o.strategy for o in options} == {"SWAP", "DELAY", "CANCEL"}
    assert all(0 <= o.score <= 100 for o in options)
    assert any(o.pareto_efficient for o in options if o.feasible)


def test_optimizer_selects_feasible_best_candidate(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)
    optimization = optimize_recovery_options(options)

    assert optimization.best_strategy is not None
    assert optimization.candidates
    assert optimization.candidates[0].objective_score <= optimization.candidates[-1].objective_score
    assert all(option.objective_score >= 0 for option in options if option.feasible)


def test_recovery_preserves_crew_residuals(schedule_df, dependency_graph):
    result = run_cascade(dependency_graph, "QR052", 90.0)
    assert any(event.edge_type == "CREW" for event in result.events)

    options = {opt.strategy: opt for opt in evaluate_all_recovery_options(dependency_graph, schedule_df, result)}
    crew_event = next(event for event in result.events if event.edge_type == "CREW")

    for strategy in ("SWAP", "DELAY"):
        option = options[strategy]
        assert any(event.edge_type == "CREW" for event in option.residual_events)

        row = option.df_recovered[option.df_recovered["flight_id"] == crew_event.flight_id].iloc[0]
        if row["direction"] == "inbound":
            assert row["arr_delay_min"] >= crew_event.delay_min
        else:
            assert row["dep_delay_min"] >= crew_event.delay_min


def test_recovery_preserves_outbound_trigger_delay(schedule_df, dependency_graph):
    outbound_id = schedule_df[schedule_df["direction"] == "outbound"].iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, outbound_id, 45.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)

    for option in options:
        if option.df_recovered is None:
            continue
        row = option.df_recovered[option.df_recovered["flight_id"] == outbound_id].iloc[0]
        assert row["status"] == "trigger"
        assert row["dep_delay_min"] == pytest.approx(45.0)


def test_monte_carlo_and_heatmap_shapes(schedule_df, dependency_graph):
    mc = run_monte_carlo(dependency_graph, schedule_df, n_scenarios=25, seed=42)
    assert mc.network_summary is not None
    assert mc.n_scenarios == 25
    assert len(mc.delay_samples) == 25
    assert len(mc.cost_samples) == 25

    heatmap = build_heatmap_data(mc, dependency_graph)
    assert len(heatmap["x"]) == dependency_graph.number_of_nodes()
    assert len(heatmap["y"]) == 4
    assert len(heatmap["z"]) == 4
    assert len(heatmap["annots"]) == 4


def test_pdf_generation_smoke(schedule_df, dependency_graph, tmp_path: Path):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    cascade_result = run_cascade(dependency_graph, trigger_id, 25.0)
    recovery_options = evaluate_all_recovery_options(dependency_graph, schedule_df, cascade_result)
    mc = run_monte_carlo(dependency_graph, schedule_df, n_scenarios=10, seed=42)

    cascade_dict = cascade_result.summary()
    cascade_dict["events"] = [
        {
            "flight_id": e.flight_id,
            "direction": "outbound",
            "edge_type": e.edge_type,
            "delay_min": e.delay_min,
            "pax_affected": e.pax_affected,
            "cost_usd": e.cost_usd,
            "severity": e.severity,
        }
        for e in cascade_result.events
    ]

    options_dict = [
        {
            "label": o.label,
            "feasible": o.feasible,
            "delay_reduction_min": o.delay_reduction_min,
            "delay_reduction_pct": o.delay_reduction_pct,
            "direct_cost_usd": o.direct_cost_usd,
            "net_cost_usd": o.net_cost_usd,
            "pax_saved": o.pax_saved,
            "score": o.score,
        }
        for o in recovery_options
    ]

    out = tmp_path / "silsila_smoke_report.pdf"
    written_path = generate_pdf_report(cascade_dict, options_dict, mc, str(out))

    assert written_path == str(out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_deserialize_mc_store_rebuilds_summary_and_profiles():
    mc_store = """{
        "n_scenarios": 12,
        "mean_flights_affected": 2.5,
        "p50_flights_affected": 2.0,
        "p90_flights_affected": 5.0,
        "p99_flights_affected": 7.0,
        "mean_cost_usd": 1000,
        "p50_cost_usd": 900,
        "p90_cost_usd": 2000,
        "p99_cost_usd": 3000,
        "mean_total_delay": 44.0,
        "p90_total_delay": 90.0,
        "zero_cascade_pct": 25.0,
        "critical_scenario_pct": 8.0,
        "top_triggers": [["QR021", 12345.0]],
        "risk_profiles": {
            "QR021": {
                "risk_label": "HIGH",
                "risk_score": 0.42,
                "victim_probability": 0.33,
                "trigger_avg_cost": 12345.0,
                "direction": "inbound",
                "origin": "KJFK",
                "destination": "OTHH",
                "aircraft_type": "A350-1000"
            }
        }
    }"""

    mc = deserialize_mc_store(mc_store)

    assert mc is not None
    assert mc.n_scenarios == 12
    assert mc.network_summary.n_scenarios == 12
    assert mc.network_summary.top_triggers == [["QR021", 12345.0]]
    assert mc.risk_profiles["QR021"].risk_label == "HIGH"


def test_cascade_store_round_trip_preserves_events(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 25.0)

    payload = serialize_cascade_result(result, dependency_graph)
    restored = deserialize_cascade_store(payload)

    assert restored is not None
    assert restored["trigger"] == trigger_id
    assert restored["trigger_delay_min"] == 25.0
    assert len(restored["events"]) == len(result.events)
    if restored["events"]:
        first = restored["events"][0]
        assert first["direction"] in {"inbound", "outbound"}
        assert "propagation_path" in first


def test_recovery_options_serialize_for_export(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)

    payload = serialize_recovery_options(options)
    restored = deserialize_recovery_store(payload)

    assert len(restored) == 3
    assert {item["strategy"] for item in restored} == {"SWAP", "DELAY", "CANCEL"}
    assert all("label" in item and "score" in item for item in restored)
    assert all("pareto_efficient" in item for item in restored)
    assert all("objective_score" in item for item in restored)


def test_turnaround_sensitivity_returns_ordered_scenarios(schedule_df):
    points = run_turnaround_sensitivity(
        schedule_df,
        trigger_ids=["QR007", "QR021"],
        trigger_delay_min=60.0,
        min_turnaround_values=[35.0, 45.0, 55.0],
    )

    assert [point.min_turnaround_min for point in points] == [35.0, 45.0, 55.0]
    assert all(point.scenario_count == 2 for point in points)
    assert points[-1].mean_flights_affected >= points[0].mean_flights_affected
