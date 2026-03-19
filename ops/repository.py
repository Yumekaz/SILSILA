from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from threading import Lock
from typing import Any


class OpsRepository:
    """SQLite persistence for scenarios, jobs, and append-only audit logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenario_runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    trigger_flight TEXT NOT NULL,
                    delay_min REAL NOT NULL,
                    state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    data_quality TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    confidence_label TEXT NOT NULL,
                    confidence_reasons TEXT NOT NULL,
                    request_payload TEXT NOT NULL,
                    cascade_payload TEXT NOT NULL,
                    recovery_payload TEXT NOT NULL,
                    selected_strategy TEXT,
                    decision_note TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    scenario_id TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    details TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events is append-only');
                END;

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    job_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    result_payload TEXT,
                    error_message TEXT
                );
                """
            )

    def save_scenario_run(self, payload: dict[str, Any]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO scenario_runs (
                    id, created_at, updated_at, trigger_flight, delay_min, state,
                    actor, actor_role, model_version, data_source, data_quality,
                    confidence_score, confidence_label, confidence_reasons,
                    request_payload, cascade_payload, recovery_payload,
                    selected_strategy, decision_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"], payload["created_at"], payload["updated_at"], payload["trigger_flight"],
                    payload["delay_min"], payload["state"], payload["actor"], payload["actor_role"],
                    payload["model_version"], payload["data_source"], payload["data_quality"],
                    payload["confidence_score"], payload["confidence_label"], payload["confidence_reasons"],
                    payload["request_payload"], payload["cascade_payload"], payload["recovery_payload"],
                    payload.get("selected_strategy"), payload.get("decision_note"),
                ),
            )

    def update_scenario_state(
        self,
        scenario_id: str,
        state: str,
        selected_strategy: str | None = None,
        note: str | None = None,
    ) -> bool:
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE scenario_runs
                SET updated_at = ?, state = ?, selected_strategy = COALESCE(?, selected_strategy), decision_note = COALESCE(?, decision_note)
                WHERE id = ?
                """,
                (now, state, selected_strategy, note, scenario_id),
            )
        return cursor.rowcount > 0

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM scenario_runs WHERE id = ?", (scenario_id,)).fetchone()
        return self._decode_scenario_row(row) if row else None

    def list_recent_scenarios(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scenario_runs ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self._decode_scenario_row(row) for row in rows]

    def append_audit_event(
        self,
        *,
        event_id: str,
        created_at: str,
        scenario_id: str | None,
        event_type: str,
        actor: str,
        actor_role: str,
        details: dict[str, Any],
    ) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (id, created_at, scenario_id, event_type, actor, actor_role, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, created_at, scenario_id, event_type, actor, actor_role, json.dumps(details)),
            )

    def list_audit_events(self, scenario_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if scenario_id:
            query = "SELECT * FROM audit_events WHERE scenario_id = ? ORDER BY created_at DESC LIMIT ?"
            params = (scenario_id, int(limit))
        else:
            query = "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?"
            params = (int(limit),)
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details"]) if item.get("details") else {}
            results.append(item)
        return results

    def create_job(self, payload: dict[str, Any]) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, created_at, started_at, finished_at, job_type, state, actor, actor_role, metadata, result_payload, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"], payload["created_at"], payload.get("started_at"), payload.get("finished_at"),
                    payload["job_type"], payload["state"], payload["actor"], payload["actor_role"],
                    payload["metadata"], payload.get("result_payload"), payload.get("error_message"),
                ),
            )

    def update_job(self, job_id: str, **updates: Any) -> bool:
        if not updates:
            return False
        fields = []
        values = []
        for key, value in updates.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        with self._lock, self._connection() as conn:
            cursor = conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        return cursor.rowcount > 0

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"]) if item.get("metadata") else {}
        item["result_payload"] = json.loads(item["result_payload"]) if item.get("result_payload") else None
        return item

    def job_counts(self) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute("SELECT state, COUNT(*) AS count FROM jobs GROUP BY state").fetchall()
        return {row["state"]: int(row["count"]) for row in rows}

    def _decode_scenario_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["confidence_reasons"] = json.loads(item["confidence_reasons"]) if item.get("confidence_reasons") else []
        item["request_payload"] = json.loads(item["request_payload"]) if item.get("request_payload") else {}
        item["cascade_payload"] = json.loads(item["cascade_payload"]) if item.get("cascade_payload") else {}
        item["recovery_payload"] = json.loads(item["recovery_payload"]) if item.get("recovery_payload") else []
        return item
