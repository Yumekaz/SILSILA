from __future__ import annotations

from flask import jsonify, request

from ops.auth import require_role, resolve_request_user



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

    @server.get("/healthz")
    def silsila_healthz():
        return jsonify(platform.health_snapshot())

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
        use_opensky = payload.get("use_opensky")
        if use_opensky is not None:
            use_opensky = bool(use_opensky)
        result = platform.refresh_runtime_from_source(use_opensky=use_opensky, actor=user.username, actor_role=user.role)
        return jsonify(result)

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
        flight_id = payload.get("flight_id")
        delay_min = payload.get("delay_min")
        if not flight_id or delay_min is None:
            return jsonify({"error": "flight_id and delay_min are required."}), 400
        execution = platform.run_simulation(flight_id, float(delay_min), actor=user.username, actor_role=user.role)
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
            return jsonify({"error": "state must be REVIEWED, RECOMMENDED, ACCEPTED, or OVERRIDDEN."}), 400
        if state == "RECOMMENDED":
            strategy = payload.get("selected_strategy")
            if not strategy:
                return jsonify({"error": "selected_strategy is required for RECOMMENDED state."}), 400
            platform.record_recovery_selection(scenario_id, str(strategy), actor=user.username, actor_role=user.role)
        else:
            platform.record_workflow_transition(scenario_id, state, actor=user.username, actor_role=user.role, note=note)
        scenario = platform.get_scenario(scenario_id)
        return jsonify({"scenario_id": scenario_id, "state": state, "scenario": scenario})

    @server.post("/api/jobs/monte-carlo")
    def silsila_api_queue_monte_carlo():
        try:
            user = _authorize({"operator", "admin"})
        except PermissionError as exc:
            return _error_response(exc)
        payload = request.get_json(silent=True) or {}
        n_scenarios = max(1, int(payload.get("n_scenarios", 100)))
        job_id = platform.submit_monte_carlo_job(n_scenarios=n_scenarios, actor=user.username, actor_role=user.role)
        return jsonify({"job_id": job_id, "state": "QUEUED"}), 202

    @server.get("/api/jobs/<job_id>")
    def silsila_api_get_job(job_id: str):
        try:
            _authorize({"viewer", "operator", "admin"})
        except PermissionError as exc:
            return _error_response(exc)
        job = platform.repository.get_job(job_id)
        if job is None:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(job)
