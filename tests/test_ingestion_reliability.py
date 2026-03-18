from __future__ import annotations

from datetime import datetime, timezone

import engine.data_loader as data_loader
from engine.data_loader import build_synthetic_schedule, load_schedule



def test_synthetic_schedule_carries_ingestion_metadata():
    df = build_synthetic_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc))
    meta = df.attrs.get("ingestion_metadata", {})

    assert df.attrs["data_source"] == "synthetic-hub-schedule"
    assert meta.get("provider") == "synthetic"
    assert meta.get("fallback_active") is True
    assert meta.get("mode") == "FALLBACK"



def test_hybrid_schedule_carries_ingestion_metadata(monkeypatch):
    date = datetime(2026, 3, 11, tzinfo=timezone.utc)
    partial = load_schedule(date, use_opensky=False)
    partial = partial[partial["direction"] == "inbound"].head(6).copy()
    partial["flight_id"] = [f"QTR9{idx:02d}" for idx in range(len(partial))]
    partial["origin"] = [f"ORIG{idx}" for idx in range(len(partial))]
    partial.attrs["data_source"] = "opensky-arrivals-partial"
    partial.attrs["ingestion_metadata"] = {
        "provider": "opensky",
        "outcome": "SUCCESS",
        "mode": "LIVE",
        "fallback_active": False,
        "attempts": 1,
        "records_received": len(partial),
        "circuit_state": "CLOSED",
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "freshness_warn_s": 900,
        "freshness_degrade_s": 3600,
    }

    monkeypatch.setattr(data_loader, "fetch_from_opensky", lambda _: partial)

    blended = load_schedule(date, use_opensky=True)
    meta = blended.attrs.get("ingestion_metadata", {})

    assert blended.attrs["data_source"].startswith("opensky-hybrid-")
    assert meta.get("mode") == "HYBRID"
    assert meta.get("outcome") == "HYBRID"
    assert meta.get("fallback_active") is False



def test_failed_live_fetch_falls_back_with_reason(monkeypatch):
    date = datetime(2026, 3, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(data_loader, "fetch_from_opensky", lambda _: None)
    monkeypatch.setattr(
        data_loader,
        "get_last_feed_metadata",
        lambda: {
            "provider": "opensky",
            "outcome": "ERROR",
            "mode": "FALLBACK",
            "fallback_active": True,
            "error": "timeout talking to upstream",
            "circuit_state": "OPEN",
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            "freshness_warn_s": 900,
            "freshness_degrade_s": 3600,
        },
    )

    schedule = load_schedule(date, use_opensky=True)
    meta = schedule.attrs.get("ingestion_metadata", {})

    assert schedule.attrs["data_source"] == "synthetic-hub-schedule"
    assert meta.get("fallback_active") is True
    assert meta.get("mode") == "FALLBACK"
    assert any("timeout" in reason for reason in schedule.attrs.get("degraded_reasons", []))
