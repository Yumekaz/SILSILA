from __future__ import annotations

from datetime import datetime, timezone

import networkx as nx

from engine.cascade import run_cascade
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph


def test_synthetic_schedule_supports_multiple_legs_per_aircraft():
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)

    legs_per_aircraft = schedule_df.groupby("aircraft_reg")["flight_id"].count()

    assert schedule_df.attrs["data_source"] == "synthetic-hub-schedule"
    assert legs_per_aircraft.max() >= 4
    assert (legs_per_aircraft >= 4).sum() >= 4


def test_graph_contains_return_sector_rotation_edges():
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)
    dependency_graph = build_graph(schedule_df)

    return_edges = [
        (u, v, data)
        for u, v, data in dependency_graph.edges(data=True)
        if data.get("edge_type") == "ROTATION" and data.get("rotation_context") == "return_sector"
    ]

    assert return_edges
    for u, v, data in return_edges:
        upstream = schedule_df[schedule_df["flight_id"] == u].iloc[0]
        downstream = schedule_df[schedule_df["flight_id"] == v].iloc[0]
        assert upstream["direction"] == "outbound"
        assert downstream["direction"] == "inbound"
        assert upstream["destination"] == downstream["origin"]
        assert data["slack_min"] >= 0


def test_cascade_propagates_across_multiple_rotation_hops():
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)
    dependency_graph = build_graph(schedule_df)

    result = run_cascade(dependency_graph, "QR007", 90.0)
    paths = {event.flight_id: event.propagation_path for event in result.events}

    assert result.max_depth >= 3
    assert "QR008" in paths
    assert "QR107" in paths
    assert "QR108" in paths
    assert paths["QR107"] == ["QR007", "QR008", "QR107"]
    assert paths["QR108"] == ["QR007", "QR008", "QR107", "QR108"]


def test_cascade_preserves_secondary_passenger_impacts_on_already_delayed_flights():
    dependency_graph = nx.DiGraph()
    dependency_graph.add_node("TRIG", pax=100)
    dependency_graph.add_node("MID", pax=80)
    dependency_graph.add_node("BANK", pax=120)

    dependency_graph.add_edge("TRIG", "MID", edge_type="ROTATION", slack_min=0)
    dependency_graph.add_edge("TRIG", "BANK", edge_type="ROTATION", slack_min=10)
    dependency_graph.add_edge("MID", "BANK", edge_type="PAX_CNXN", slack_min=5, connecting_pax=30)

    result = run_cascade(dependency_graph, "TRIG", 20.0)
    bank_event = next(event for event in result.events if event.flight_id == "BANK")

    assert bank_event.delay_min == 10.0
    assert bank_event.pax_stranded == 30
    assert set(bank_event.impact_channels) == {"ROTATION", "PAX_CNXN"}
    assert result.total_pax_stranded == 30
