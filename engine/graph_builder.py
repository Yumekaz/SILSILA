"""
graph_builder.py
----------------
Converts the DOH schedule DataFrame into a directed NetworkX graph.

Node  = one flight (inbound OR outbound)
Edges = dependency relationships:
  - ROTATION:   same aircraft, inbound → outbound (physical constraint)
  - CREW:       same crew, inbound → outbound (legal duty constraint)
  - PAX_CNXN:   passenger minimum connection time (commercial constraint)

Edge weight = vulnerability score (0–1).
Higher weight = delay propagates more aggressively through this edge.
"""

import networkx as nx
import pandas as pd
from datetime import datetime, timedelta, timezone

from engine.config import (
    MIN_TURNAROUND_MINUTES,
    MIN_PAX_CONNECT_MIN,
    COST_PAX_PER_MIN,
    COST_AIRCRAFT_PER_MIN
)


def build_graph(df: pd.DataFrame) -> nx.DiGraph:
    """
    Build a directed dependency graph from a DOH schedule DataFrame.

    Returns a DiGraph where:
      - Nodes carry full flight metadata
      - Edges carry type, constraint values, and vulnerability weight
    """
    G = nx.DiGraph()

    # ── Add nodes ─────────────────────────────────────────────────────────────
    for _, row in df.iterrows():
        # Compute a reference time (arr for inbound, dep for outbound)
        ref_time = row["arr_actual"] if row["direction"] == "inbound" else row["dep_scheduled"]

        G.add_node(
            row["flight_id"],
            direction=row["direction"],
            origin=row["origin"],
            destination=row["destination"],
            aircraft_reg=row["aircraft_reg"],
            aircraft_type=row["aircraft_type"],
            crew_id=row["crew_id"],
            seats=int(row["seats"]),
            pax=int(row["pax"]),
            load_factor=float(row["load_factor"]),
            arr_scheduled=row.get("arr_scheduled", pd.NaT),
            arr_actual=row.get("arr_actual", pd.NaT),
            dep_scheduled=row.get("dep_scheduled", pd.NaT),
            dep_actual=row.get("dep_actual", pd.NaT),
            arr_delay_min=float(row.get("arr_delay_min", 0)),
            dep_delay_min=float(row.get("dep_delay_min", 0)),
            turnaround_slack_min=float(row.get("turnaround_slack_min", 0)),
            status=row["status"],
            ref_time=ref_time,
            # Cascade state (mutated during simulation)
            cascade_delay_min=0.0,
            cascade_reason="",
        )

    inbound_flights  = df[df["direction"] == "inbound"]
    outbound_flights = df[df["direction"] == "outbound"]

    # ── ROTATION edges ─────────────────────────────────────────────────────────
    # Same aircraft: inbound → outbound
    for _, inb in inbound_flights.iterrows():
        matching_out = outbound_flights[outbound_flights["aircraft_reg"] == inb["aircraft_reg"]]
        for _, oub in matching_out.iterrows():
            arr_actual    = inb["arr_actual"]
            dep_scheduled = oub["dep_scheduled"]

            if pd.isna(arr_actual) or pd.isna(dep_scheduled):
                continue

            # Turnaround slack: how many buffer minutes exist above the minimum
            slack_min = (dep_scheduled - arr_actual).total_seconds() / 60 - MIN_TURNAROUND_MINUTES

            # Vulnerability: tight turnaround = high vulnerability
            vulnerability = max(0.0, min(1.0, 1.0 - (slack_min / 90.0)))

            G.add_edge(
                inb["flight_id"],
                oub["flight_id"],
                edge_type="ROTATION",
                aircraft_reg=inb["aircraft_reg"],
                slack_min=round(slack_min, 1),
                min_required_min=MIN_TURNAROUND_MINUTES,
                vulnerability=round(vulnerability, 3),
                label=f"Rotation {inb['aircraft_reg']} | slack {slack_min:.0f}m",
            )

    # ── CREW edges ─────────────────────────────────────────────────────────────
    # Same crew: inbound → outbound (different aircraft handled later)
    for _, inb in inbound_flights.iterrows():
        matching_out = outbound_flights[
            (outbound_flights["crew_id"] == inb["crew_id"]) &
            (outbound_flights["aircraft_reg"] != inb["aircraft_reg"])
        ]
        for _, oub in matching_out.iterrows():
            if pd.isna(inb["arr_actual"]) or pd.isna(oub["dep_scheduled"]):
                continue
            slack_min    = (oub["dep_scheduled"] - inb["arr_actual"]).total_seconds() / 60
            vulnerability = max(0.0, min(1.0, 1.0 - (slack_min / 120.0)))

            G.add_edge(
                inb["flight_id"],
                oub["flight_id"],
                edge_type="CREW",
                crew_id=inb["crew_id"],
                slack_min=round(slack_min, 1),
                min_required_min=60,
                vulnerability=round(vulnerability, 3),
                label=f"Crew {inb['crew_id']} | slack {slack_min:.0f}m",
            )

    # ── PAX_CNXN edges ─────────────────────────────────────────────────────────
    # Passengers from each inbound can connect to outbounds departing > MIN_PAX_CONNECT_MIN later
    for _, inb in inbound_flights.iterrows():
        if pd.isna(inb["arr_actual"]):
            continue
        earliest_dep = inb["arr_actual"] + timedelta(minutes=MIN_PAX_CONNECT_MIN)

        for _, oub in outbound_flights.iterrows():
            if pd.isna(oub["dep_scheduled"]):
                continue
            # Only flights where passengers might realistically connect
            connection_window_min = (oub["dep_scheduled"] - inb["arr_actual"]).total_seconds() / 60
            if not (MIN_PAX_CONNECT_MIN <= connection_window_min <= 180):
                continue
            # Skip if already linked by ROTATION (same aircraft = no connection)
            if inb["aircraft_reg"] == oub["aircraft_reg"]:
                continue

            # Estimate connecting pax (rough heuristic: 8-15% of inbound pax per viable outbound)
            connecting_pax = max(5, int(inb["pax"] * 0.10))
            buffer_min     = connection_window_min - MIN_PAX_CONNECT_MIN
            vulnerability  = max(0.0, min(1.0, 1.0 - (buffer_min / 90.0)))

            G.add_edge(
                inb["flight_id"],
                oub["flight_id"],
                edge_type="PAX_CNXN",
                connecting_pax=connecting_pax,
                connection_window_min=round(connection_window_min, 1),
                min_required_min=MIN_PAX_CONNECT_MIN,
                slack_min=round(buffer_min, 1),
                vulnerability=round(vulnerability, 3),
                label=f"Pax cnxn | ~{connecting_pax} pax | buffer {buffer_min:.0f}m",
            )

    return G


def graph_summary(G: nx.DiGraph) -> dict:
    """Human-readable summary of the graph for logging/display."""
    edge_types = {}
    for _, _, d in G.edges(data=True):
        t = d.get("edge_type", "UNKNOWN")
        edge_types[t] = edge_types.get(t, 0) + 1

    return {
        "nodes":      G.number_of_nodes(),
        "edges":      G.number_of_edges(),
        "edge_types": edge_types,
        "inbound":    sum(1 for n, d in G.nodes(data=True) if d.get("direction") == "inbound"),
        "outbound":   sum(1 for n, d in G.nodes(data=True) if d.get("direction") == "outbound"),
    }


def compute_node_positions(G: nx.DiGraph) -> dict:
    """
    Compute 2D positions for Plotly network graph rendering.

    Layout:
      - X axis = reference time (hour of day, 0–24)
      - Y axis = aircraft index (each aircraft gets its own row)
      - Inbound nodes are placed slightly left of center-time
      - Outbound nodes slightly right

    Returns: {flight_id: (x, y)}
    """
    aircraft_list = sorted(set(
        d["aircraft_reg"] for _, d in G.nodes(data=True)
    ))
    aircraft_y = {reg: i for i, reg in enumerate(aircraft_list)}

    positions = {}
    for flight_id, data in G.nodes(data=True):
        ref = data.get("ref_time")
        if ref is None or str(ref) == "NaT":
            # Fallback to a mid-day-ish UTC time if missing
            x = datetime.now(tz=timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        else:
            x = ref

        y = aircraft_y.get(data.get("aircraft_reg", ""), 0)

        # Spread inbound/outbound slightly on Y for readability
        if data.get("direction") == "inbound":
            y += 0.15
        else:
            y -= 0.15

        positions[flight_id] = (x, round(y, 3))

    return positions
