from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import tempfile
import time
import uuid
from typing import Any

import pandas as pd

from engine.config import USE_OPENSKY_BY_DEFAULT
from engine.data_loader import REQUIRED_COLUMNS, load_schedule
from engine.graph_builder import build_graph, graph_summary
from engine.monte_carlo import run_monte_carlo
from engine.pdf_report import generate_pdf_report
from engine.sensitivity import run_turnaround_sensitivity
from engine.validation import validate_graph, validate_schedule
from ops.jobs import BackgroundJobManager
from ops.observability import MetricsRegistry
from ops.repository import OpsRepository
from ops.settings import OpsSettings, load_ops_settings
from ui.session_state import (
    deserialize_cascade_store,
    deserialize_mc_store,
    deserialize_recovery_store,
    serialize_cascade_result,
    serialize_recovery_options,
)
from ui.workflows import prepare_pdf_export_bundle, run_simulation_bundle


@dataclass(frozen=True)
class DataQualityStatus:
    status: str
    mode: str
    source_label: str
    warnings: list[str]
    loaded_at: str
    freshness_seconds: int
    completeness_ratio: float
    feed_provider: str = "unknown"
    feed_outcome: str = "unknown"
    circuit_state: str = "CLOSED"
    fallback_active: bool = False


@dataclass(frozen=True)
class ConfidenceScore:
    score: float
    label: str
    reasons: list[str]


@dataclass(frozen=True)
class SimulationExecution:
    scenario_id: str
    bundle: Any
    confidence: ConfidenceScore


class OpsPlatform:
    def __init__(self, df, graph, settings: OpsSettings | None = None) -> None:
        self.settings = settings or load_ops_settings()
        self.metrics = MetricsRegistry()
        self.repository = OpsRepository(self.settings.db_path)
        self.jobs = BackgroundJobManager(self.repository, self.metrics, max_workers=self.settings.max_workers)
        self.refresh_runtime(df, graph)

    def refresh_runtime(self, df, graph) -> None:
        self.df = df
        self.graph = graph
        self.loaded_at = datetime.now(tz=timezone.utc)
        self.schedule_report = validate_schedule(df)
        self.graph_report = validate_graph(graph)
        self.graph_snapshot = graph_summary(graph)
        self.data_quality = _assess_data_quality(df, self.schedule_report, self.loaded_at)
        self.metrics.set_gauge("schedule_flights", len(df))
        self.metrics.set_gauge("graph_nodes", self.graph_snapshot.get("nodes", 0))
        self.metrics.set_gauge("graph_edges", self.graph_snapshot.get("edges", 0))
        self.metrics.set_gauge("data_completeness_ratio", self.data_quality.completeness_ratio)

    def refresh_runtime_from_source(
        self,
        *,
        use_opensky: bool | None = None,
        actor: str = "api",
        actor_role: str = "admin",
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        runtime_date = datetime.now(tz=timezone.utc)
        runtime_df = load_schedule(runtime_date, use_opensky=USE_OPENSKY_BY_DEFAULT if use_opensky is None else use_opensky)
        runtime_graph = build_graph(runtime_df)
        self.refresh_runtime(runtime_df, runtime_graph)
        duration = time.perf_counter() - t0
        self._record_duration("runtime_refresh", duration)
        self._append_audit(
            scenario_id=None,
            event_type="runtime.refresh",
            actor=actor,
            actor_role=actor_role,
            details={
                "use_opensky": bool(use_opensky if use_opensky is not None else USE_OPENSKY_BY_DEFAULT),
                "data_source": self.data_quality.source_label,
                "data_quality": self.data_quality.status,
                "mode": self.data_quality.mode,
            },
        )
        return {
            "data_quality": asdict(self.data_quality),
            "graph_summary": self.graph_snapshot,
            "duration_ms": round(duration * 1000, 1),
        }

    def run_simulation(self, flight_id: str, delay_min: float, actor: str = "dashboard", actor_role: str = "system") -> SimulationExecution:
        t0 = time.perf_counter()
        bundle = run_simulation_bundle(self.graph, self.df, flight_id, float(delay_min))
        confidence = _compute_confidence(bundle, self.data_quality, self.schedule_report, self.graph_report)
        scenario_id = uuid.uuid4().hex
        created_at = datetime.now(tz=timezone.utc).isoformat()

        cascade_payload = deserialize_cascade_store(serialize_cascade_result(bundle.cascade_result, self.graph)) or {}
        recovery_payload = deserialize_recovery_store(serialize_recovery_options(bundle.recovery_options))
        request_payload = {
            "trigger_flight": flight_id,
            "delay_min": float(delay_min),
            "graph_nodes": self.graph_snapshot.get("nodes", 0),
            "graph_edges": self.graph_snapshot.get("edges", 0),
        }

        self.repository.save_scenario_run(
            {
                "id": scenario_id,
                "created_at": created_at,
                "updated_at": created_at,
                "trigger_flight": flight_id,
                "delay_min": float(delay_min),
                "state": "SIMULATED",
                "actor": actor,
                "actor_role": actor_role,
                "model_version": self.settings.model_version,
                "data_source": self.data_quality.source_label,
                "data_quality": self.data_quality.status,
                "confidence_score": confidence.score,
                "confidence_label": confidence.label,
                "confidence_reasons": json.dumps(confidence.reasons),
                "request_payload": json.dumps(request_payload),
                "cascade_payload": json.dumps(cascade_payload),
                "recovery_payload": json.dumps(recovery_payload),
            }
        )
        self._append_audit(
            scenario_id=scenario_id,
            event_type="simulation.run",
            actor=actor,
            actor_role=actor_role,
            details={
                "trigger_flight": flight_id,
                "delay_min": float(delay_min),
                "confidence": asdict(confidence),
            },
        )
        self.metrics.increment("simulation_runs")
        self._record_duration("simulation", time.perf_counter() - t0)
        return SimulationExecution(scenario_id=scenario_id, bundle=bundle, confidence=confidence)

    def record_recovery_selection(self, scenario_id: str, strategy: str, actor: str = "dashboard", actor_role: str = "operator") -> None:
        self.repository.update_scenario_state(scenario_id, "RECOMMENDED", selected_strategy=strategy)
        self._append_audit(
            scenario_id=scenario_id,
            event_type="recovery.selected",
            actor=actor,
            actor_role=actor_role,
            details={"selected_strategy": strategy},
        )
        self.metrics.increment("recovery_selections")

    def record_workflow_transition(
        self,
        scenario_id: str,
        state: str,
        actor: str = "dashboard",
        actor_role: str = "operator",
        note: str | None = None,
    ) -> None:
        self.repository.update_scenario_state(scenario_id, state, note=note)
        self._append_audit(
            scenario_id=scenario_id,
            event_type="workflow.transition",
            actor=actor,
            actor_role=actor_role,
            details={"state": state, "note": note or ""},
        )
        self.metrics.increment(f"workflow_{state.lower()}")

    def run_monte_carlo_sync(self, n_scenarios: int | None = None, actor: str = "dashboard", actor_role: str = "system"):
        t0 = time.perf_counter()
        mc = run_monte_carlo(self.graph, self.df, n_scenarios=n_scenarios or 500)
        self._append_audit(
            scenario_id=None,
            event_type="monte_carlo.run",
            actor=actor,
            actor_role=actor_role,
            details={"n_scenarios": mc.n_scenarios, "top_triggers": mc.network_summary.top_triggers if mc.network_summary else []},
        )
        self.metrics.increment("monte_carlo_runs")
        self._record_duration("monte_carlo", time.perf_counter() - t0)
        return mc

    def submit_monte_carlo_job(self, n_scenarios: int, actor: str = "api", actor_role: str = "operator") -> str:
        return self.jobs.submit(
            job_type="monte_carlo",
            actor=actor,
            actor_role=actor_role,
            metadata={"n_scenarios": int(n_scenarios)},
            fn=lambda: self._mc_summary(self.run_monte_carlo_sync(n_scenarios=n_scenarios, actor=actor, actor_role=actor_role)),
        )

    def run_sensitivity_sync(
        self,
        *,
        flight_id: str,
        delay_min: float,
        actor: str = "dashboard",
        actor_role: str = "system",
        min_turnaround_values: list[float] | None = None,
    ):
        t0 = time.perf_counter()
        points = run_turnaround_sensitivity(
            self.df,
            trigger_ids=[flight_id],
            trigger_delay_min=float(delay_min),
            min_turnaround_values=min_turnaround_values or [35.0, 45.0, 55.0, 65.0],
        )
        self._append_audit(
            scenario_id=None,
            event_type="sensitivity.run",
            actor=actor,
            actor_role=actor_role,
            details={"flight_id": flight_id, "delay_min": float(delay_min), "points": len(points)},
        )
        self.metrics.increment("sensitivity_runs")
        self._record_duration("sensitivity", time.perf_counter() - t0)
        return points

    def generate_pdf_bytes(
        self,
        *,
        flight_id: str,
        delay_min: float,
        cascade_store: str | None,
        recovery_store: str | None,
        selected_recovery_store: str | None,
        mc_store: str | None,
        actor: str = "dashboard",
        actor_role: str = "system",
    ) -> tuple[bytes, str]:
        t0 = time.perf_counter()
        export_bundle = prepare_pdf_export_bundle(
            self.graph,
            self.df,
            flight_id,
            float(delay_min),
            cascade_store,
            recovery_store,
            selected_recovery_store,
        )
        mc = deserialize_mc_store(mc_store)
        if mc is None:
            mc = self.run_monte_carlo_sync(actor=actor, actor_role=actor_role)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            path = tmp.name
        try:
            generate_pdf_report(export_bundle.cascade_payload, export_bundle.recovery_payload, mc, path)
            with open(path, "rb") as handle:
                pdf_bytes = handle.read()
        finally:
            if os.path.exists(path):
                os.unlink(path)
        filename = (
            f"SILSILA_{flight_id}_{int(delay_min)}min_"
            f"{export_bundle.cascade_payload.get('flights_affected', 0)}affected.pdf"
        )
        self._append_audit(
            scenario_id=None,
            event_type="report.export",
            actor=actor,
            actor_role=actor_role,
            details={"filename": filename, "trigger_flight": flight_id, "delay_min": float(delay_min)},
        )
        self.metrics.increment("pdf_exports")
        self._record_duration("pdf_export", time.perf_counter() - t0)
        return pdf_bytes, filename

    def recent_scenarios(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.repository.list_recent_scenarios(limit=limit)

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        scenario = self.repository.get_scenario(scenario_id)
        if not scenario:
            return None
        scenario["audit_events"] = self.repository.list_audit_events(scenario_id=scenario_id, limit=50)
        return scenario

    def health_snapshot(self) -> dict[str, Any]:
        freshness_seconds = int((datetime.now(tz=timezone.utc) - self.loaded_at).total_seconds())
        data_quality = {
            **asdict(self.data_quality),
            "freshness_seconds": freshness_seconds,
        }
        job_counts = self.repository.job_counts()
        alerts = list(self.data_quality.warnings)
        if self.metrics.snapshot().get("counters", {}).get("response_slo_breaches", 0):
            alerts.append("One or more timed operations exceeded the configured response SLO.")
        overall = "NOMINAL"
        if not self.schedule_report.passed or not self.graph_report.passed:
            overall = "FAILED"
        elif self.data_quality.status != "NOMINAL":
            overall = "DEGRADED"
        return {
            "status": overall,
            "environment": self.settings.environment,
            "model_version": self.settings.model_version,
            "response_slo_ms": self.settings.response_slo_ms,
            "data_quality": data_quality,
            "ingestion_metadata": dict(self.df.attrs.get("ingestion_metadata", {})),
            "alerts": alerts,
            "schedule_validation": asdict(self.schedule_report),
            "graph_validation": asdict(self.graph_report),
            "graph_summary": self.graph_snapshot,
            "job_counts": job_counts,
            "metrics": self.metrics.snapshot(),
            "recent_scenarios": self.recent_scenarios(limit=5),
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        snapshot = self.metrics.snapshot()
        snapshot["response_slo_ms"] = self.settings.response_slo_ms
        snapshot["job_counts"] = self.repository.job_counts()
        return snapshot

    def _mc_summary(self, mc) -> dict[str, Any]:
        ns = mc.network_summary
        return {
            "n_scenarios": mc.n_scenarios,
            "runtime_seconds": ns.runtime_seconds if ns else 0.0,
            "mean_flights_affected": ns.mean_flights_affected if ns else 0.0,
            "p90_cost_usd": ns.p90_cost_usd if ns else 0.0,
            "critical_scenario_pct": ns.critical_scenario_pct if ns else 0.0,
            "top_triggers": ns.top_triggers if ns else [],
        }

    def _record_duration(self, name: str, seconds: float) -> None:
        self.metrics.observe(f"{name}_seconds", seconds)
        elapsed_ms = seconds * 1000
        self.metrics.set_gauge(f"{name}_last_ms", elapsed_ms)
        if elapsed_ms > self.settings.response_slo_ms:
            self.metrics.increment("response_slo_breaches")
            self.metrics.increment(f"{name}_slo_breaches")

    def _append_audit(self, *, scenario_id: str | None, event_type: str, actor: str, actor_role: str, details: dict[str, Any]) -> None:
        self.repository.append_audit_event(
            event_id=uuid.uuid4().hex,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
            scenario_id=scenario_id,
            event_type=event_type,
            actor=actor,
            actor_role=actor_role,
            details=details,
        )



def _assess_data_quality(df, schedule_report, loaded_at: datetime) -> DataQualityStatus:
    ingestion_meta = dict(df.attrs.get("ingestion_metadata", {}))
    source = str(df.attrs.get("data_source", "synthetic-hub-schedule")).replace("-", " ").upper()
    warnings = list(schedule_report.warnings)
    warnings.extend(str(item) for item in df.attrs.get("degraded_reasons", []) if item)

    required_cols_present = len(REQUIRED_COLUMNS.intersection(df.columns))
    schema_ratio = required_cols_present / len(REQUIRED_COLUMNS)

    non_null_columns = [
        column for column in ("flight_id", "direction", "origin", "destination", "aircraft_reg", "pax")
        if column in df.columns
    ]
    if non_null_columns and not df.empty:
        non_null_ratio = sum(float(df[column].notna().mean()) for column in non_null_columns) / len(non_null_columns)
    else:
        non_null_ratio = 0.0
    completeness_ratio = round(min(1.0, (schema_ratio * 0.6) + (non_null_ratio * 0.4)), 2)

    raw_source = str(df.attrs.get("data_source", "synthetic-hub-schedule"))
    outcome = str(ingestion_meta.get("outcome", "UNKNOWN")).upper()
    provider = str(ingestion_meta.get("provider", "unknown"))
    circuit_state = str(ingestion_meta.get("circuit_state", "CLOSED"))
    fallback_active = bool(ingestion_meta.get("fallback_active", False))

    fetched_at_raw = ingestion_meta.get("fetched_at") or df.attrs.get("loaded_at") or loaded_at.isoformat()
    try:
        fetched_at = datetime.fromisoformat(str(fetched_at_raw))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    except ValueError:
        fetched_at = loaded_at
    freshness_seconds = max(0, int((loaded_at - fetched_at).total_seconds()))

    if raw_source.startswith("opensky-hybrid") or outcome == "HYBRID":
        status = "PARTIAL"
        mode = "HYBRID"
        warnings.append("Hybrid schedule blends authoritative arrivals with modeled downstream legs.")
    elif raw_source.startswith("opensky") and not fallback_active:
        status = "NOMINAL"
        mode = "LIVE"
    else:
        status = "DEGRADED"
        mode = "FALLBACK"
        warnings.append("Synthetic fallback schedule is active.")

    if circuit_state == "OPEN":
        status = "DEGRADED"
        warnings.append("Upstream feed circuit breaker is open after repeated failures.")
    if freshness_seconds >= int(ingestion_meta.get("freshness_degrade_s", 3600)) and mode != "FALLBACK":
        status = "DEGRADED"
        warnings.append("Live data is stale beyond the degrade threshold.")
    elif freshness_seconds >= int(ingestion_meta.get("freshness_warn_s", 900)) and status == "NOMINAL":
        status = "PARTIAL"
        warnings.append("Live data is older than the preferred freshness window.")
    if completeness_ratio < 0.85 and status == "NOMINAL":
        status = "PARTIAL"
        warnings.append("Schedule completeness ratio dropped below 85%.")
    if not schedule_report.passed:
        status = "DEGRADED"

    deduped_warnings = list(dict.fromkeys(warnings))
    return DataQualityStatus(
        status=status,
        mode=mode,
        source_label=source,
        warnings=deduped_warnings,
        loaded_at=loaded_at.isoformat(),
        freshness_seconds=freshness_seconds,
        completeness_ratio=completeness_ratio,
        feed_provider=provider,
        feed_outcome=outcome,
        circuit_state=circuit_state,
        fallback_active=fallback_active,
    )



def _compute_confidence(bundle, data_quality: DataQualityStatus, schedule_report, graph_report) -> ConfidenceScore:
    score = 0.9
    reasons = [f"Data mode: {data_quality.mode}"]
    if data_quality.status == "PARTIAL":
        score -= 0.12
        reasons.append("Hybrid or stale live data increases uncertainty.")
    elif data_quality.status == "DEGRADED":
        score -= 0.28
        reasons.append("Synthetic fallback or feed degradation reduces operational fidelity.")
    if schedule_report.warnings:
        score -= 0.04 * len(schedule_report.warnings)
        reasons.extend(schedule_report.warnings)
    if graph_report.warnings:
        score -= 0.03 * len(graph_report.warnings)
        reasons.extend(graph_report.warnings)
    if data_quality.completeness_ratio < 0.9:
        score -= 0.05
        reasons.append("Schedule completeness is below the preferred threshold.")
    if bundle.cascade_result.max_depth >= 3:
        score -= 0.03
        reasons.append("Deep multi-hop cascade increases uncertainty.")
    score = max(0.35, min(score, 0.98))
    if score >= 0.8:
        label = "HIGH"
    elif score >= 0.6:
        label = "MEDIUM"
    else:
        label = "LOW"
    return ConfidenceScore(score=round(score, 2), label=label, reasons=list(dict.fromkeys(reasons)))



def build_ops_platform(df, graph, settings: OpsSettings | None = None) -> OpsPlatform:
    return OpsPlatform(df, graph, settings=settings)
