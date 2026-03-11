from __future__ import annotations

from datetime import datetime, timezone

from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from engine.historical_validation import (
    HISTORICAL_VALIDATION_CASES,
    run_historical_validation_case,
    run_historical_validation_suite,
)


def test_historical_validation_suite_passes_curated_cases():
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)
    dependency_graph = build_graph(schedule_df)

    suite = run_historical_validation_suite(schedule_df=schedule_df, graph=dependency_graph)

    assert suite.total_cases == 5
    assert suite.passed_cases == 5
    assert suite.pass_rate_pct == 100.0


def test_historical_validation_frame_exposes_benchmark_metrics():
    suite = run_historical_validation_suite(date=datetime(2026, 3, 11, tzinfo=timezone.utc))
    frame = suite.to_frame()

    assert list(frame["case_id"]) == [case.case_id for case in HISTORICAL_VALIDATION_CASES]
    assert {"analog_trigger_id", "edge_types", "passed", "score_pct"}.issubset(frame.columns)
    assert frame["passed"].all()


def test_crew_incident_case_requires_multi_channel_propagation():
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)
    dependency_graph = build_graph(schedule_df)
    case = next(case for case in HISTORICAL_VALIDATION_CASES if case.case_id == "HV-05")

    result = run_historical_validation_case(case, schedule_df=schedule_df, graph=dependency_graph)

    assert result.passed
    assert set(case.required_edge_types).issubset(set(result.edge_types))
    assert result.summary["critical_count"] >= 2
