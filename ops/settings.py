from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


ENV_PREFIX = "SILSILA_"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OpsSettings:
    db_path: Path
    auth_required: bool
    api_tokens: str
    max_workers: int
    environment: str
    model_version: str
    response_slo_ms: int
    feature_api: bool
    feature_jobs: bool
    feature_workflow: bool
    feature_metrics: bool



def load_ops_settings() -> OpsSettings:
    db_path = Path(os.getenv(f"{ENV_PREFIX}DB_PATH", "data/runtime/silsila_ops.db"))
    return OpsSettings(
        db_path=db_path,
        auth_required=_env_bool(f"{ENV_PREFIX}AUTH_REQUIRED", False),
        api_tokens=os.getenv(f"{ENV_PREFIX}API_TOKENS", ""),
        max_workers=max(1, int(os.getenv(f"{ENV_PREFIX}MAX_WORKERS", "2"))),
        environment=os.getenv(f"{ENV_PREFIX}ENVIRONMENT", "local"),
        model_version=os.getenv(f"{ENV_PREFIX}MODEL_VERSION", "cascade-v2.0"),
        response_slo_ms=max(250, int(os.getenv(f"{ENV_PREFIX}RESPONSE_SLO_MS", "2500"))),
        feature_api=_env_bool(f"{ENV_PREFIX}FEATURE_API", True),
        feature_jobs=_env_bool(f"{ENV_PREFIX}FEATURE_JOBS", True),
        feature_workflow=_env_bool(f"{ENV_PREFIX}FEATURE_WORKFLOW", True),
        feature_metrics=_env_bool(f"{ENV_PREFIX}FEATURE_METRICS", True),
    )
