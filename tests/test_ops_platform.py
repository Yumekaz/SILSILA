from __future__ import annotations

from datetime import datetime, timezone
import time

import pytest

from app import create_app
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from ops.services import build_ops_platform
from ops.settings import OpsSettings


@pytest.fixture()
def schedule_df():
    return load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)


@pytest.fixture()
def dependency_graph(schedule_df):
    return build_graph(schedule_df)


@pytest.fixture()
def ops_settings(tmp_path):
    return OpsSettings(
        db_path=tmp_path / "silsila_ops.db",
        auth_required=False,
        api_tokens="",
        max_workers=2,
        environment="test",
        model_version="test-model",
        response_slo_ms=1500,
        feature_api=True,
        feature_jobs=True,
        feature_workflow=True,
        feature_metrics=True,
    )


@pytest.fixture()
def platform(schedule_df, dependency_graph, ops_settings):
    return build_ops_platform(schedule_df, dependency_graph, settings=ops_settings)



def test_platform_persists_simulation_and_audit(platform):
    execution = platform.run_simulation("QR021", 30.0, actor="pytest", actor_role="admin")
    scenario = platform.get_scenario(execution.scenario_id)

    assert scenario is not None
    assert scenario["trigger_flight"] == "QR021"
    assert scenario["state"] == "SIMULATED"
    assert scenario["confidence_label"] in {"HIGH", "MEDIUM", "LOW"}
    assert any(event["event_type"] == "simulation.run" for event in scenario["audit_events"])



def test_platform_logs_recovery_selection_and_workflow_transition(platform):
    execution = platform.run_simulation("QR021", 30.0, actor="pytest", actor_role="admin")
    platform.record_recovery_selection(execution.scenario_id, "SWAP", actor="pytest", actor_role="admin")
    platform.record_workflow_transition(execution.scenario_id, "REVIEWED", actor="pytest", actor_role="admin", note="Checked by test")
    scenario = platform.get_scenario(execution.scenario_id)

    assert scenario is not None
    assert scenario["state"] == "REVIEWED"
    assert scenario["selected_strategy"] == "SWAP"
    assert any(event["event_type"] == "recovery.selected" for event in scenario["audit_events"])
    assert any(event["event_type"] == "workflow.transition" for event in scenario["audit_events"])



def test_api_health_and_scenario_endpoints(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.get_json()["data_quality"]["status"] in {"NOMINAL", "PARTIAL", "DEGRADED"}

    created = client.post("/api/scenarios", json={"flight_id": "QR021", "delay_min": 45})
    assert created.status_code == 201
    scenario_id = created.get_json()["scenario_id"]

    fetched = client.get(f"/api/scenarios/{scenario_id}")
    assert fetched.status_code == 200
    payload = fetched.get_json()
    assert payload["trigger_flight"] == "QR021"
    assert payload["delay_min"] == 45.0
    assert payload["audit_events"]



def test_api_auth_required_blocks_requests(tmp_path, schedule_df, dependency_graph):
    settings = OpsSettings(
        db_path=tmp_path / "auth_ops.db",
        auth_required=True,
        api_tokens="secret|ops-admin|admin",
        max_workers=1,
        environment="test",
        model_version="test-model",
        response_slo_ms=1500,
        feature_api=True,
        feature_jobs=True,
        feature_workflow=True,
        feature_metrics=True,
    )
    secured_platform = build_ops_platform(schedule_df, dependency_graph, settings=settings)
    app = create_app(schedule_df, dependency_graph, platform=secured_platform)
    client = app.server.test_client()

    unauthorized = client.get("/api/health")
    assert unauthorized.status_code == 401

    authorized = client.get("/api/health", headers={"X-API-Key": "secret"})
    assert authorized.status_code == 200



def test_runtime_refresh_endpoint_returns_updated_health(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    response = client.post("/api/runtime/refresh", json={"use_opensky": False}, headers={"X-Role": "admin"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data_quality"]["mode"] == "FALLBACK"
    assert payload["graph_summary"]["nodes"] > 0


def test_monte_carlo_job_endpoint_completes(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    queued = client.post("/api/jobs/monte-carlo", json={"n_scenarios": 5})
    assert queued.status_code == 202
    job_id = queued.get_json()["job_id"]

    final_payload = None
    for _ in range(40):
        time.sleep(0.1)
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        final_payload = response.get_json()
        if final_payload["state"] in {"COMPLETED", "FAILED"}:
            break

    assert final_payload is not None
    assert final_payload["state"] == "COMPLETED"
    assert final_payload["result_payload"]["n_scenarios"] == 5

