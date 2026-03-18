# Deployment

## Recommended Platform

Render is the best fit for the current codebase.

Why:

- the app is a long-running Python web process, not a serverless function
- the repo already exposes a WSGI entrypoint in `server.py`
- the app persists scenarios, jobs, and audit events locally, so it benefits from a persistent disk
- synthetic fallback keeps the service usable even when the public data path is unavailable

Vercel is not the right primary target for this version because the app is stateful and Gunicorn-based.

## Included Deployment Artifacts

- `render.yaml`
- `Procfile`
- `runtime.txt`
- `gunicorn.conf.py`

## Render Blueprint

The repo now includes a Render Blueprint that:

- deploys a Python web service
- starts Gunicorn with an explicit `PORT` binding
- uses `/healthz` for zero-downtime health checks
- mounts a persistent disk at `/var/data`
- stores the SQLite runtime DB at `/var/data/silsila_ops.db`
- enables API, jobs, workflow, and metrics by default

Current start command:

```bash
gunicorn server:server --config gunicorn.conf.py
```

## Render Deploy Steps

1. Push the repo to GitHub.
2. In Render, create a new Blueprint or Web Service from the repo root.
3. Let Render read `render.yaml`.
4. Confirm the persistent disk mount at `/var/data`.
5. Deploy.

After first deploy, verify:

- `/healthz`
- `/api/health`
- `/api/runtime/refresh`

## Important Environment Variables

- `SILSILA_DB_PATH=/var/data/silsila_ops.db`
- `SILSILA_ENVIRONMENT=production`
- `SILSILA_MODEL_VERSION=cascade-v2.0-render`
- `SILSILA_RESPONSE_SLO_MS=2500`
- `SILSILA_MAX_WORKERS=2`
- `SILSILA_USE_OPENSKY_BY_DEFAULT=false`

Gunicorn tuning env vars are also supported:

- `WEB_CONCURRENCY`
- `GUNICORN_THREADS`
- `GUNICORN_TIMEOUT`
- `GUNICORN_GRACEFUL_TIMEOUT`
- `GUNICORN_KEEPALIVE`

## Notes

- The current deployment path uses SQLite on a persistent Render disk. That is fine for a single-instance deploy.
- Because persistent disks cannot scale horizontally on Render, this service should remain single-instance in the current architecture.
- If public live data is unavailable, the app will degrade cleanly into synthetic fallback mode.
- If you want a more serious multi-instance production deployment later, the repository layer should be migrated from SQLite to Postgres.
