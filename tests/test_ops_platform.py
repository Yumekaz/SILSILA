from __future__ import annotations

from datetime import datetime, timezone
import importlib
import sys
import time

import pytest

from app import create_app
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from ops.services import ScenarioNotFoundError, WorkflowTransitionError, build_ops_platform
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

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    assert set(healthz.get_json()) == {"status", "environment", "model_version", "data_quality", "alerts"}

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



def test_root_layout_and_probe_endpoints_respond(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    root = client.get("/")
    assert root.status_code == 200

    layout = client.get("/_dash-layout")
    assert layout.status_code == 200
    layout_payload = layout.get_json()
    assert "props" in layout_payload
    assert "children" in layout_payload["props"]

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    assert healthz.get_json()["status"] in {"NOMINAL", "PARTIAL", "DEGRADED"}


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

    probe = client.get("/healthz")
    assert probe.status_code == 200

    unauthorized = client.get("/api/health")
    assert unauthorized.status_code == 401

    authorized = client.get("/api/health", headers={"X-API-Key": "secret"})
    assert authorized.status_code == 200



def test_runtime_refresh_endpoint_returns_updated_health(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    response = client.post("/api/runtime/refresh", json={"use_opensky": "false"}, headers={"X-Role": "admin"})
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


@pytest.mark.parametrize(
    ("payload", "expected_status", "message"),
    [
        ({}, 400, "flight_id and delay_min are required"),
        ({"flight_id": "QR021", "delay_min": "abc"}, 400, "delay_min must be a numeric value"),
        ({"flight_id": "QR021", "delay_min": 0}, 400, "delay_min must be greater than 0"),
        ({"flight_id": "NOPE", "delay_min": 30}, 404, "flight_id was not found"),
    ],
)
def test_api_create_scenario_rejects_invalid_requests(platform, schedule_df, dependency_graph, payload, expected_status, message):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    response = client.post("/api/scenarios", json=payload)

    assert response.status_code == expected_status
    assert message in response.get_json()["error"]


def test_api_workflow_returns_404_for_missing_scenario(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    response = client.post(
        "/api/scenarios/missing/workflow",
        json={"state": "RECOMMENDED", "selected_strategy": "SWAP"},
    )

    assert response.status_code == 404
    assert "missing" in response.get_json()["error"].lower()


def test_api_workflow_rejects_invalid_transition(platform, schedule_df, dependency_graph):
    app = create_app(schedule_df, dependency_graph, platform=platform)
    client = app.server.test_client()

    created = client.post("/api/scenarios", json={"flight_id": "QR021", "delay_min": 45})
    scenario_id = created.get_json()["scenario_id"]

    response = client.post(
        f"/api/scenarios/{scenario_id}/workflow",
        json={"state": "ACCEPTED", "note": "Skipping review"},
    )

    assert response.status_code == 409
    assert "invalid workflow transition" in response.get_json()["error"].lower()


def test_platform_rejects_missing_and_invalid_workflow_updates(platform):
    with pytest.raises(ScenarioNotFoundError):
        platform.record_recovery_selection("missing", "SWAP")

    execution = platform.run_simulation("QR021", 30.0, actor="pytest", actor_role="admin")
    with pytest.raises(WorkflowTransitionError):
        platform.record_workflow_transition(execution.scenario_id, "ACCEPTED", actor="pytest", actor_role="admin")


def test_feature_flags_disable_optional_routes(tmp_path, schedule_df, dependency_graph):
    settings = OpsSettings(
        db_path=tmp_path / "feature-flags.db",
        auth_required=False,
        api_tokens="",
        max_workers=1,
        environment="test",
        model_version="flags",
        response_slo_ms=1500,
        feature_api=True,
        feature_jobs=False,
        feature_workflow=False,
        feature_metrics=False,
    )
    restricted_platform = build_ops_platform(schedule_df, dependency_graph, settings=settings)
    app = create_app(schedule_df, dependency_graph, platform=restricted_platform)
    client = app.server.test_client()
    routes = {rule.rule for rule in app.server.url_map.iter_rules()}

    assert restricted_platform.jobs is None
    assert "/api/metrics" not in routes
    assert "/api/jobs/monte-carlo" not in routes
    assert "/api/scenarios/<scenario_id>/workflow" not in routes
    assert client.get("/api/health").status_code == 200


def test_server_entrypoint_boots_and_exposes_healthz(monkeypatch, tmp_path):
    monkeypatch.setenv("SILSILA_DB_PATH", str(tmp_path / "server-entrypoint.db"))
    monkeypatch.setenv("SILSILA_USE_OPENSKY_BY_DEFAULT", "false")
    sys.modules.pop("server", None)

    server_module = importlib.import_module("server")
    server_module = importlib.reload(server_module)
    client = server_module.server.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json()["status"] in {"NOMINAL", "DEGRADED", "FAILED"}

