from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.data_loader import REQUIRED_COLUMNS, load_schedule
from engine.graph_builder import build_graph, graph_summary
from engine.cascade import run_cascade, cascaded_schedule
from engine.recovery import evaluate_all_recovery_options
from engine.monte_carlo import run_monte_carlo, build_heatmap_data
from engine.pdf_report import generate_pdf_report


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


def test_graph_builds_and_has_core_edge_types(dependency_graph):
    summary = graph_summary(dependency_graph)
    assert summary["nodes"] > 0
    assert summary["edges"] > 0
    for edge_type in ("ROTATION", "PAX_CNXN", "CREW"):
        assert summary["edge_types"].get(edge_type, 0) >= 1


def test_cascade_pipeline_returns_consistent_outputs(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    cascaded_df = cascaded_schedule(schedule_df, dependency_graph, result)

    assert result.trigger_flight == trigger_id
    assert result.trigger_delay_min == 30.0
    assert len(cascaded_df) == len(schedule_df)
    assert "status" in cascaded_df.columns


def test_recovery_options_are_ranked_and_complete(schedule_df, dependency_graph):
    trigger_id = schedule_df.iloc[0]["flight_id"]
    result = run_cascade(dependency_graph, trigger_id, 30.0)
    options = evaluate_all_recovery_options(dependency_graph, schedule_df, result)

    assert len(options) == 3
    assert all(options[i].score >= options[i + 1].score for i in range(len(options) - 1))
    assert {o.strategy for o in options} == {"SWAP", "DELAY", "CANCEL"}
    assert all(0 <= o.score <= 100 for o in options)


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
