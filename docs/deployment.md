# Deployment

## Current State

- The project is runnable locally.
- A basic Render deployment config is included in the repo.
- No confirmed live deployment URL is stored in the repository.

## Render

The repo now includes `render.yaml`.

Expected start command:

```bash
gunicorn app:server
```

## Notes

- The deployed service will use the same runtime path as local execution.
- If real-data APIs are unavailable, the app will still function using the synthetic schedule.
- A production deployment should add environment-specific logging and health checks.
