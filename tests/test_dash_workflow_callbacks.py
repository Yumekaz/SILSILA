from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app import create_app
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from ops.services import build_ops_platform
from ops.settings import OpsSettings


def _build_app(tmp_path: Path):
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)
    dependency_graph = build_graph(schedule_df)
    settings = OpsSettings(
        db_path=tmp_path / "dash-callbacks.db",
        auth_required=False,
        api_tokens="",
        max_workers=2,
        environment="test",
        model_version="dash-callbacks",
        response_slo_ms=1500,
        feature_api=True,
        feature_jobs=True,
        feature_workflow=True,
        feature_metrics=True,
    )
    platform = build_ops_platform(schedule_df, dependency_graph, settings=settings)
    app = create_app(schedule_df, dependency_graph, platform=platform)
    return app, platform


def _callback_key(app, first_input_id: str) -> str:
    return next(
        key
        for key, spec in app.callback_map.items()
        if spec.get("inputs") and spec["inputs"][0]["id"] == first_input_id
    )


def test_dash_callback_workflow_round_trip(tmp_path):
    app, platform = _build_app(tmp_path)
    client = app.server.test_client()

    simulate_key = _callback_key(app, "trigger-btn")
    simulate_response = client.post(
        "/_dash-update-component",
        json={
            "output": simulate_key,
            "outputs": [
                {"id": "cascade-result-store", "property": "data"},
                {"id": "scenario-id-store", "property": "data"},
                {"id": "operator-state-store", "property": "data"},
                {"id": "network-graph", "property": "elements"},
                {"id": "network-graph", "property": "stylesheet"},
                {"id": "graph-empty-state", "property": "style"},
                {"id": "cascade-log", "property": "children"},
                {"id": "affected-count", "property": "children"},
                {"id": "gantt-chart", "property": "figure"},
                {"id": "summary-metrics", "property": "children"},
                {"id": "recovery-cards", "property": "children"},
                {"id": "recovery-status-badge", "property": "children"},
                {"id": "recovery-comparison-strip", "property": "children"},
                {"id": "operator-state-badge", "property": "children"},
                {"id": "workflow-activity-note", "property": "children"},
                {"id": "optimizer-summary", "property": "children"},
                {"id": "recovery-options-store", "property": "data"},
                {"id": "selected-recovery-store", "property": "data"},
            ],
            "changedPropIds": ["trigger-btn.n_clicks"],
            "inputs": [
                {"id": "trigger-btn", "property": "n_clicks", "value": 1},
                {"id": "reset-btn", "property": "n_clicks", "value": 0},
            ],
            "state": [
                {"id": "flight-select", "property": "value", "value": "QR021"},
                {"id": "delay-slider", "property": "value", "value": 30},
            ],
        },
    )
    assert simulate_response.status_code == 200

    simulate_payload = simulate_response.get_json()["response"]
    scenario_id = simulate_payload["scenario-id-store"]["data"]
    cascade_store = simulate_payload["cascade-result-store"]["data"]
    recovery_store = simulate_payload["recovery-options-store"]["data"]

    scenario = platform.get_scenario(scenario_id)
    assert scenario is not None
    assert scenario["state"] == "SIMULATED"
    assert scenario["trigger_flight"] == "QR021"

    apply_key = _callback_key(app, '{"index":0,"type":"recovery-select-btn"}')
    apply_response = client.post(
        "/_dash-update-component",
        json={
            "output": apply_key,
            "outputs": [
                {"id": "gantt-chart", "property": "figure"},
                {"id": "network-graph", "property": "elements"},
                {"id": "selected-recovery-store", "property": "data"},
                {"id": "recovery-comparison-strip", "property": "children"},
                {"id": "operator-state-store", "property": "data"},
                {"id": "operator-state-badge", "property": "children"},
                {"id": "workflow-activity-note", "property": "children"},
            ],
            "changedPropIds": ['{"index":0,"type":"recovery-select-btn"}.n_clicks'],
            "inputs": [
                {"id": '{"index":0,"type":"recovery-select-btn"}', "property": "n_clicks", "value": 1},
                {"id": '{"index":1,"type":"recovery-select-btn"}', "property": "n_clicks", "value": 0},
                {"id": '{"index":2,"type":"recovery-select-btn"}', "property": "n_clicks", "value": 0},
            ],
            "state": [
                {"id": "flight-select", "property": "value", "value": "QR021"},
                {"id": "delay-slider", "property": "value", "value": 30},
                {"id": "recovery-options-store", "property": "data", "value": recovery_store},
                {"id": "cascade-result-store", "property": "data", "value": cascade_store},
                {"id": "scenario-id-store", "property": "data", "value": scenario_id},
            ],
        },
    )
    assert apply_response.status_code == 200

    apply_payload = apply_response.get_json()["response"]
    selected_recovery_store = apply_payload["selected-recovery-store"]["data"]
    scenario = platform.get_scenario(scenario_id)
    assert scenario is not None
    assert scenario["state"] == "RECOMMENDED"
    assert scenario["selected_strategy"]

    review_key = _callback_key(app, "mark-reviewed-btn")
    review_response = client.post(
        "/_dash-update-component",
        json={
            "output": review_key,
            "outputs": [
                {"id": "operator-state-store", "property": "data"},
                {"id": "operator-state-badge", "property": "children"},
                {"id": "workflow-activity-note", "property": "children"},
            ],
            "changedPropIds": ["mark-reviewed-btn.n_clicks"],
            "inputs": [
                {"id": "mark-reviewed-btn", "property": "n_clicks", "value": 1},
                {"id": "accept-plan-btn", "property": "n_clicks", "value": 0},
                {"id": "override-plan-btn", "property": "n_clicks", "value": 0},
            ],
            "state": [
                {"id": "scenario-id-store", "property": "data", "value": scenario_id},
                {"id": "selected-recovery-store", "property": "data", "value": selected_recovery_store},
            ],
        },
    )
    assert review_response.status_code == 200

    scenario = platform.get_scenario(scenario_id)
    assert scenario is not None
    assert scenario["state"] == "REVIEWED"
    assert any(event["event_type"] == "workflow.transition" for event in scenario["audit_events"])
