from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import json
import time
import uuid
from threading import Lock
from typing import Any, Callable


class BackgroundJobManager:
    def __init__(self, repository, metrics, max_workers: int = 2) -> None:
        self._repository = repository
        self._metrics = metrics
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="silsila-job")
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit(
        self,
        *,
        job_type: str,
        actor: str,
        actor_role: str,
        metadata: dict[str, Any],
        fn: Callable[[], dict[str, Any]],
    ) -> str:
        job_id = uuid.uuid4().hex
        created_at = datetime.now(tz=timezone.utc).isoformat()
        self._repository.create_job(
            {
                "id": job_id,
                "created_at": created_at,
                "job_type": job_type,
                "state": "QUEUED",
                "actor": actor,
                "actor_role": actor_role,
                "metadata": json.dumps(metadata),
            }
        )
        future = self._executor.submit(self._run_job, job_id, job_type, actor, actor_role, fn)
        with self._lock:
            self._futures[job_id] = future
        self._metrics.increment("jobs_submitted")
        self._metrics.set_gauge("jobs_inflight", self.inflight_count())
        return job_id

    def inflight_count(self) -> int:
        with self._lock:
            self._futures = {job_id: future for job_id, future in self._futures.items() if not future.done()}
            return len(self._futures)

    def _run_job(
        self,
        job_id: str,
        job_type: str,
        actor: str,
        actor_role: str,
        fn: Callable[[], dict[str, Any]],
    ) -> None:
        started_at = datetime.now(tz=timezone.utc).isoformat()
        self._repository.update_job(job_id, started_at=started_at, state="RUNNING")
        t0 = time.perf_counter()
        try:
            result = fn()
            finished_at = datetime.now(tz=timezone.utc).isoformat()
            self._repository.update_job(
                job_id,
                finished_at=finished_at,
                state="COMPLETED",
                result_payload=json.dumps(result),
            )
            self._metrics.increment(f"job_{job_type}_completed")
        except Exception as exc:  # pragma: no cover - failure path still logged/testable via API
            finished_at = datetime.now(tz=timezone.utc).isoformat()
            self._repository.update_job(
                job_id,
                finished_at=finished_at,
                state="FAILED",
                error_message=str(exc),
            )
            self._metrics.increment(f"job_{job_type}_failed")
        finally:
            self._metrics.observe(f"job_{job_type}_seconds", time.perf_counter() - t0)
            self._metrics.set_gauge("jobs_inflight", self.inflight_count())
