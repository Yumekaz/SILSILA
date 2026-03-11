"""
graph_builder.py
----------------
Converts the DOH schedule DataFrame into a directed NetworkX graph.

Node  = one flight (inbound OR outbound)
Edges = dependency relationships:
  - ROTATION: sequential same-aircraft legs across hub turns and return sectors
  - CREW:     same crew, inbound -> outbound (legal duty constraint)
  - PAX_CNXN: passenger minimum connection time (commercial constraint)

Edge weight = vulnerability score (0-1).
Higher weight = delay propagates more aggressively through this edge.
"""

from datetime import datetime, timedelta, timezone

import networkx as nx
import pandas as pd

from engine.config import MAX_CREW_CONNECT_MIN, MIN_PAX_CONNECT_MIN, MIN_TURNAROUND_MINUTES


def build_graph(df: pd.DataFrame) -> nx.DiGraph:
    """Build a directed dependency graph from a DOH schedule DataFrame."""
    return build_graph_with_constraints(df, min_turnaround_minutes=MIN_TURNAROUND_MINUTES)


def build_graph_with_constraints(
    df: pd.DataFrame,
    min_turnaround_minutes: float = MIN_TURNAROUND_MINUTES,
) -> nx.DiGraph:
    """Build a graph with a configurable minimum turnaround assumption."""
    graph = nx.DiGraph()

    for _, row in df.iterrows():
        ref_time = row["arr_actual"] if row["direction"] == "inbound" else row["dep_scheduled"]
        aircraft_reg = str(row.get("aircraft_reg", "A7-UNK")).upper()
        seats = int(row.get("seats", 0) or 0)
        load_factor = float(row.get("load_factor", 0.0) or 0.0)
        pax = int(row.get("pax", 0) or 0)

        graph.add_node(
            row["flight_id"],
            direction=row["direction"],
            origin=row["origin"],
            destination=row["destination"],
            aircraft_reg=aircraft_reg,
            aircraft_type=row.get("aircraft_type", "UNKNOWN"),
            crew_id=row.get("crew_id", "CREW-UNK"),
            seats=seats,
            pax=pax,
            load_factor=load_factor,
            arr_scheduled=row.get("arr_scheduled", pd.NaT),
            arr_actual=row.get("arr_actual", pd.NaT),
            dep_scheduled=row.get("dep_scheduled", pd.NaT),
            dep_actual=row.get("dep_actual", pd.NaT),
            arr_delay_min=float(row.get("arr_delay_min", 0)),
            dep_delay_min=float(row.get("dep_delay_min", 0)),
            turnaround_slack_min=float(row.get("turnaround_slack_min", 0)),
            status=row["status"],
            block_time_h=float(row.get("block_time_h", 0.0) or 0.0),
            ref_time=ref_time,
            cascade_delay_min=0.0,
            cascade_reason="",
        )

    inbound_flights = df[df["direction"] == "inbound"]
    outbound_flights = df[df["direction"] == "outbound"]

    _add_rotation_edges(graph, df, min_turnaround_minutes)

    for _, inb in inbound_flights.iterrows():
        matching_out = outbound_flights[
            (outbound_flights["crew_id"] == inb["crew_id"])
            & (outbound_flights["aircraft_reg"] != inb["aircraft_reg"])
        ]
        for _, out in matching_out.iterrows():
            if pd.isna(inb["arr_actual"]) or pd.isna(out["dep_scheduled"]):
                continue
            slack_min = (out["dep_scheduled"] - inb["arr_actual"]).total_seconds() / 60
            if not (60 <= slack_min <= MAX_CREW_CONNECT_MIN):
                continue
            vulnerability = max(0.0, min(1.0, 1.0 - (slack_min / 120.0)))

            graph.add_edge(
                inb["flight_id"],
                out["flight_id"],
                edge_type="CREW",
                crew_id=inb["crew_id"],
                slack_min=round(slack_min, 1),
                min_required_min=60,
                vulnerability=round(vulnerability, 3),
                label=f"Crew {inb['crew_id']} | slack {slack_min:.0f}m",
            )

    for _, inb in inbound_flights.iterrows():
        if pd.isna(inb["arr_actual"]):
            continue
        for _, out in outbound_flights.iterrows():
            if pd.isna(out["dep_scheduled"]):
                continue
            if graph.has_edge(inb["flight_id"], out["flight_id"]):
                continue
            connection_window_min = (out["dep_scheduled"] - inb["arr_actual"]).total_seconds() / 60
            if not (MIN_PAX_CONNECT_MIN <= connection_window_min <= 180):
                continue
            if inb["aircraft_reg"] == out["aircraft_reg"]:
                continue

            connecting_pax = max(5, int(inb["pax"] * 0.10))
            buffer_min = connection_window_min - MIN_PAX_CONNECT_MIN
            vulnerability = max(0.0, min(1.0, 1.0 - (buffer_min / 90.0)))

            graph.add_edge(
                inb["flight_id"],
                out["flight_id"],
                edge_type="PAX_CNXN",
                connecting_pax=connecting_pax,
                connection_window_min=round(connection_window_min, 1),
                min_required_min=MIN_PAX_CONNECT_MIN,
                slack_min=round(buffer_min, 1),
                vulnerability=round(vulnerability, 3),
                label=f"Pax cnxn | ~{connecting_pax} pax | buffer {buffer_min:.0f}m",
            )

    return graph


def _add_rotation_edges(graph: nx.DiGraph, df: pd.DataFrame, min_turnaround_minutes: float) -> None:
    for _, group in df.groupby("aircraft_reg"):
        ordered = group.copy()
        ordered["_ref_time"] = ordered.apply(_rotation_reference_time, axis=1)
        ordered = ordered.sort_values("_ref_time")
        ordered_rows = list(ordered.iterrows())

        for pos in range(len(ordered_rows) - 1):
            _, current = ordered_rows[pos]
            _, nxt = ordered_rows[pos + 1]
            edge_payload = _rotation_edge_payload(current, nxt, min_turnaround_minutes)
            if edge_payload is None:
                continue
            graph.add_edge(current["flight_id"], nxt["flight_id"], **edge_payload)


def _rotation_reference_time(row: pd.Series):
    return row["arr_actual"] if row["direction"] == "inbound" else row["dep_scheduled"]


def _rotation_edge_payload(current: pd.Series, nxt: pd.Series, min_turnaround_minutes: float) -> dict | None:
    if current["direction"] == "inbound" and nxt["direction"] == "outbound":
        if pd.isna(current["arr_actual"]) or pd.isna(nxt["dep_scheduled"]):
            return None
        slack_min = (nxt["dep_scheduled"] - current["arr_actual"]).total_seconds() / 60 - min_turnaround_minutes
        vulnerability = max(0.0, min(1.0, 1.0 - (slack_min / 90.0)))
        return {
            "edge_type": "ROTATION",
            "aircraft_reg": current["aircraft_reg"],
            "rotation_context": "hub_turn",
            "slack_min": round(slack_min, 1),
            "min_required_min": min_turnaround_minutes,
            "vulnerability": round(vulnerability, 3),
            "label": f"Rotation {current['aircraft_reg']} | hub slack {slack_min:.0f}m",
        }

    if current["direction"] == "outbound" and nxt["direction"] == "inbound":
        if current["destination"] != nxt["origin"]:
            return None
        if pd.isna(current["dep_scheduled"]) or pd.isna(nxt["arr_scheduled"]):
            return None
        remote_cycle_min = (current["block_time_h"] + nxt["block_time_h"]) * 60 + min_turnaround_minutes
        slack_min = (nxt["arr_scheduled"] - current["dep_scheduled"]).total_seconds() / 60 - remote_cycle_min
        vulnerability = max(0.0, min(1.0, 1.0 - (slack_min / 180.0)))
        return {
            "edge_type": "ROTATION",
            "aircraft_reg": current["aircraft_reg"],
            "rotation_context": "return_sector",
            "slack_min": round(slack_min, 1),
            "min_required_min": min_turnaround_minutes,
            "vulnerability": round(vulnerability, 3),
            "label": f"Rotation {current['aircraft_reg']} | return slack {slack_min:.0f}m",
        }

    return None


def graph_summary(graph: nx.DiGraph) -> dict:
    """Human-readable summary of the graph for logging/display."""
    edge_types = {}
    for _, _, data in graph.edges(data=True):
        edge_type = data.get("edge_type", "UNKNOWN")
        edge_types[edge_type] = edge_types.get(edge_type, 0) + 1

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "edge_types": edge_types,
        "inbound": sum(1 for _, data in graph.nodes(data=True) if data.get("direction") == "inbound"),
        "outbound": sum(1 for _, data in graph.nodes(data=True) if data.get("direction") == "outbound"),
    }


def compute_node_positions(graph: nx.DiGraph) -> dict:
    """
    Compute 2D positions for Plotly network graph rendering.

    Layout:
      - X axis = reference time (hour of day, 0-24)
      - Y axis = aircraft index (each aircraft gets its own row)
      - Inbound nodes are placed slightly left of center-time
      - Outbound nodes slightly right

    Returns: {flight_id: (x, y)}
    """
    aircraft_list = sorted({data["aircraft_reg"] for _, data in graph.nodes(data=True)})
    aircraft_y = {reg: i for i, reg in enumerate(aircraft_list)}

    positions = {}
    for flight_id, data in graph.nodes(data=True):
        ref = data.get("ref_time")
        if ref is None or str(ref) == "NaT":
            x = datetime.now(tz=timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        else:
            x = ref

        y = aircraft_y.get(data.get("aircraft_reg", ""), 0)
        if data.get("direction") == "inbound":
            y += 0.15
        else:
            y -= 0.15

        positions[flight_id] = (x, round(y, 3))

    return positions
