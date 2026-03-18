# Ops Runbook

## Health Checks
- `GET /healthz`: unauthenticated health snapshot for probes.
- `GET /api/health`: authenticated or local health snapshot with data quality, validation, queue, and metrics.
- `GET /api/metrics`: operator/admin metrics snapshot.

## Authentication
- `SILSILA_AUTH_REQUIRED=true` enables API-key enforcement.
- `SILSILA_API_TOKENS` format: `token|username|role,token2|username2|role2`.
- Roles: `viewer`, `operator`, `admin`.

## Feature Flags
- `SILSILA_FEATURE_API`
- `SILSILA_FEATURE_JOBS`
- `SILSILA_FEATURE_WORKFLOW`
- `SILSILA_FEATURE_METRICS`

## Runtime Signals
- Data quality states: `NOMINAL`, `PARTIAL`, `DEGRADED`.
- Workflow states: `SIMULATED`, `RECOMMENDED`, `REVIEWED`, `ACCEPTED`, `OVERRIDDEN`.
- Audit log is append-only at the SQLite layer.

## Incident Triage
1. Check `/healthz` for data-quality degradation and validation failures.
2. Check `/api/metrics` for long-running simulations or queue buildup.
3. Check recent scenarios in `/api/scenarios` for repeated overrides or low-confidence runs.
4. If data quality is `DEGRADED`, treat recommendations as advisory and confirm operationally.
5. If jobs are stuck in `FAILED`, inspect the latest job payload and server logs before retrying.

## Local Persistence
- Default database path: `data/runtime/silsila_ops.db`
- Scenario runs, jobs, and audit events persist across app restarts unless the DB file is removed.

## Release Discipline
- CI compiles Python modules and runs `pytest -q` on every push/PR.
- Model logic version is exposed through `SILSILA_MODEL_VERSION` and surfaced in the UI/API.
- Response-time target is set with `SILSILA_RESPONSE_SLO_MS`.
