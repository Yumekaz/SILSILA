from __future__ import annotations

from flask import jsonify, request
import math

from ops.auth import require_role, resolve_request_user
from ops.services import FeatureDisabledError, ScenarioNotFoundError, WorkflowTransitionError



def register_api(server, platform) -> None:
    if not platform.settings.feature_api:
        return

    def _authorize(allowed_roles: set[str] | None = None):
        user = resolve_request_user(request, platform.settings)
        if allowed_roles:
            require_role(user, allowed_roles)
        return user

    def _error_response(exc: PermissionError):
        status = 401 if "authentication" in str(exc).lower() else 403
        return jsonify({"error": str(exc)}), status

    def _json_error(message: str, status: int):
        return jsonify({"error": message}), status

    def _parse_bool(value):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError("use_opensky must be a boolean.")

    def _parse_delay_min(value):
        try:
            delay_min = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("delay_min must be a numeric value.") from exc
        if not math.isfinite(delay_min) or delay_min <= 0:
            raise ValueError("delay_min must be greater than 0.")
        return delay_min

    def _parse_positive_int(value, field_name: str):
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer.") from exc
        if parsed <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")
        return parsed

    @server.get("/healthz")
    def silsila_healthz():
        return jsonify(platform.public_health_snapshot())

    @server.get("/api/health")
    def silsila_api_health():
        try:
            _authorize({"viewer", "operator", "admin"})
        except PermissionError as exc:
            return _error_response(exc)
        return jsonify(platform.health_snapshot())

    @server.post("/api/runtime/refresh")
    def silsila_api_refresh_runtime():
        try:
            user = _authorize({"admin"})
        except PermissionError as exc:
            return _error_response(exc)
        payload = request.get_json(silent=True) or {}
        try:
            use_opensky = _parse_bool(payload.get("use_opensky"))
        except ValueError as exc:
            return _json_error(str(exc), 400)
        result = platform.refresh_runtime_from_source(use_opensky=use_opensky, actor=user.username, actor_role=user.role)
        return jsonify(result)

    if platform.settings.feature_metrics:
        @server.get("/api/metrics")
        def silsila_api_metrics():
            try:
                _authorize({"operator", "admin"})
            except PermissionError as exc:
                return _error_response(exc)
            return jsonify(platform.metrics_snapshot())

    @server.get("/api/scenarios")
    def silsila_api_list_scenarios():
        try:
            _authorize({"viewer", "operator", "admin"})
        except PermissionError as exc:
            return _error_response(exc)
        limit = max(1, min(50, int(request.args.get("limit", 10))))
        return jsonify({"items": platform.recent_scenarios(limit=limit)})

    @server.post("/api/scenarios")
    def silsila_api_create_scenario():
        try:
            user = _authorize({"operator", "admin"})
        except PermissionError as exc:
            return _error_response(exc)
        payload = request.get_json(silent=True) or {}
        flight_id = str(payload.get("flight_id") or "").strip().upper()
        if not flight_id:
            return _json_error("flight_id and delay_min are required.", 400)
        try:
            delay_min = _parse_delay_min(payload.get("delay_min"))
        except ValueError as exc:
            return _json_error(str(exc), 400)
        if flight_id not in platform.graph:
            return _json_error("flight_id was not found in the current dependency graph.", 404)
        try:
            execution = platform.run_simulation(flight_id, delay_min, actor=user.username, actor_role=user.role)
        except ValueError as exc:
            return _json_error(str(exc), 400)
        return jsonify(
            {
                "scenario_id": execution.scenario_id,
                "state": "SIMULATED",
                "confidence": {
                    "score": execution.confidence.score,
                    "label": execution.confidence.label,
                    "reasons": execution.confidence.reasons,
                },
                "summary": execution.bundle.cascade_result.summary(),
            }
        ), 201

    @server.get("/api/scenarios/<scenario_id>")
    def silsila_api_get_scenario(scenario_id: str):
        try:
            _authorize({"viewer", "operator", "admin"})
        except PermissionError as exc:
            return _error_response(exc)
        scenario = platform.get_scenario(scenario_id)
        if scenario is None:
            return jsonify({"error": "Scenario not found."}), 404
        return jsonify(scenario)

    if platform.settings.feature_workflow:
        @server.post("/api/scenarios/<scenario_id>/workflow")
        def silsila_api_update_workflow(scenario_id: str):
            try:
                user = _authorize({"operator", "admin"})
            except PermissionError as exc:
                return _error_response(exc)
            payload = request.get_json(silent=True) or {}
            state = str(payload.get("state") or "").upper()
            note = payload.get("note")
            if state not in {"REVIEWED", "ACCEPTED", "OVERRIDDEN", "RECOMMENDED"}:
                return _json_error("state must be REVIEWED, RECOMMENDED, ACCEPTED, or OVERRIDDEN.", 400)
            try:
                if state == "RECOMMENDED":
                    strategy = str(payload.get("selected_strategy") or "").strip().upper()
                    if not strategy:
                        return _json_error("selected_strategy is required for RECOMMENDED state.", 400)
                    platform.record_recovery_selection(scenario_id, strategy, actor=user.username, actor_role=user.role)
                else:
                    platform.record_workflow_transition(
                        scenario_id,
                        state,
                        actor=user.username,
                        actor_role=user.role,
                        note=note,
                    )
            except ScenarioNotFoundError as exc:
                return _json_error(str(exc), 404)
            except WorkflowTransitionError as exc:
                return _json_error(str(exc), 409)
            scenario = platform.get_scenario(scenario_id)
            if scenario is None:
                return _json_error("Scenario not found.", 404)
            return jsonify({"scenario_id": scenario_id, "state": state, "scenario": scenario})

    if platform.settings.feature_jobs:
        @server.post("/api/jobs/monte-carlo")
        def silsila_api_queue_monte_carlo():
            try:
                user = _authorize({"operator", "admin"})
            except PermissionError as exc:
                return _error_response(exc)
            payload = request.get_json(silent=True) or {}
            try:
                n_scenarios = _parse_positive_int(payload.get("n_scenarios", 100), "n_scenarios")
                job_id = platform.submit_monte_carlo_job(
                    n_scenarios=n_scenarios,
                    actor=user.username,
                    actor_role=user.role,
                )
            except ValueError as exc:
                return _json_error(str(exc), 400)
            except FeatureDisabledError as exc:
                return _json_error(str(exc), 404)
            return jsonify({"job_id": job_id, "state": "QUEUED"}), 202

        @server.get("/api/jobs/<job_id>")
        def silsila_api_get_job(job_id: str):
            try:
                _authorize({"viewer", "operator", "admin"})
            except PermissionError as exc:
                return _error_response(exc)
            job = platform.repository.get_job(job_id)
            if job is None:
                return _json_error("Job not found.", 404)
            return jsonify(job)
