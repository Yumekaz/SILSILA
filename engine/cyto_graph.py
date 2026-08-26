"""
cyto_graph.py
-------------
Converts the SILSILA NetworkX DiGraph into dash-cytoscape elements and
a full stylesheet. Replaces the Plotly scatter figure for the network panel.

Why cytoscape over Plotly scatter:
  - Native browser zoom (pinch/scroll) — pixel-scaled, not axis-recalculated
  - True drag-to-pan on canvas
  - Per-node click events with full data
  - CSS-class-based live restyling (cascade highlight without full re-render)
  - Node dragging for manual layout exploration
"""

import networkx as nx
import pandas as pd

# ── Brand colours (mirror CSS variables) ──────────────────────────────────────
C = {
    "bg_1":    "#14121B",
    "bg_2":    "#1C1826",
    "bg_3":    "#282034",
    "border":  "#3B2D49",
    "gold":    "#E6C78E",
    "gold_dim":"#8E7045",
    "cyan":    "#D0A7D9",
    "cyan_dim":"#765A7E",
    "teal":    "#75E0C0",
    "red":     "#FF7A86",
    "orange":  "#F3A074",
    "text_1":  "#F6F0EB",
    "text_2":  "#C3B9C7",
    "text_3":  "#82768A",
    # node status
    "normal":    "#3C2E53",
    "trigger":   "#D0A7D9",
    "delayed":   "#E6C78E",
    "delayed_h": "#F3A074",
    "critical":  "#FF7A86",
    "landed":    "#2C6656",
    "recovered": "#21856A",
    "cancelled": "#642C3B",
}

# Canvas coordinate scale: 1 hour = HOUR_PX pixels on X axis
HOUR_PX  = 34
# Each aircraft row = ROW_PX pixels apart on Y axis
ROW_PX   = 44


def build_cyto_elements(
    G: nx.DiGraph,
    df: pd.DataFrame,
    trigger_id: str | None = None,
    affected_ids: set | None = None,
) -> list:
    """
    Build the flat list of Cytoscape elements (nodes + edges).

    Node positions:
      X = reference time (arr for inbound, dep for outbound), scaled to HOUR_PX
      Y = aircraft row index * ROW_PX
      Inbound nodes: slight Y offset up
      Outbound nodes: slight Y offset down

    Node classes drive all visual styling — no per-node style overrides needed.
    """
    if affected_ids is None:
        affected_ids = set()

    # Aircraft → Y row
    aircraft_list = sorted(set(
        d["aircraft_reg"] for _, d in G.nodes(data=True)
    ))
    aircraft_y = {reg: i * ROW_PX for i, reg in enumerate(aircraft_list)}

    elements = []

    # ── Nodes ──────────────────────────────────────────────────────────────────
    for flight_id, data in G.nodes(data=True):
        direction = data.get("direction", "")
        ref_time  = data.get("arr_actual" if direction == "inbound" else "dep_scheduled")

        # X coordinate
        if ref_time is not None and str(ref_time) != "NaT":
            try:
                x = (ref_time.hour + ref_time.minute / 60.0) * HOUR_PX
            except Exception:
                x = 12 * HOUR_PX
        else:
            x = 12 * HOUR_PX

        # Y coordinate
        reg = data.get("aircraft_reg", "")
        y   = aircraft_y.get(reg, 0)
        y  += -12 if direction == "inbound" else 12

        # Status class
        status_row = df[df["flight_id"] == flight_id]
        status = status_row.iloc[0].get("status", "scheduled") if not status_row.empty else "scheduled"

        if flight_id == trigger_id:
            node_class = "trigger"
        elif status == "critical":
            node_class = "critical"
        elif status == "delayed_high":
            node_class = "delayed-high"
        elif status in ("delayed",):
            node_class = "delayed"
        elif status == "landed":
            node_class = "landed"
        elif status == "recovered":
            node_class = "recovered"
        elif status == "cancelled":
            node_class = "cancelled"
        elif flight_id in affected_ids:
            node_class = "affected"
        else:
            node_class = "normal"

        # Direction sub-class
        dir_class = "inbound" if direction == "inbound" else "outbound"

        # Node size proportional to pax
        pax  = data.get("pax", 100)
        size = 38 + int((pax / 517) * 18)   # 38–56px range

        elements.append({
            "data": {
                "id":           flight_id,
                "label":        flight_id,
                "direction":    direction,
                "origin":       data.get("origin", ""),
                "destination":  data.get("destination", ""),
                "aircraft_reg": reg,
                "aircraft_type":data.get("aircraft_type", ""),
                "pax":          pax,
                "load_factor":  data.get("load_factor", 0),
                "slack":        data.get("turnaround_slack_min", 0),
                "crew":         data.get("crew_id", ""),
                "size":         size,
                "status":       status,
            },
            "classes": f"{node_class} {dir_class}",
            "position": {"x": round(x, 1), "y": round(y, 1)},
        })

    # ── Edges ──────────────────────────────────────────────────────────────────
    for u, v, edge_data in G.edges(data=True):
        edge_type = edge_data.get("edge_type", "ROTATION")
        slack     = edge_data.get("slack_min", 0)
        vuln      = edge_data.get("vulnerability", 0)

        # Edge class drives colour + line style
        edge_class = {
            "ROTATION": "edge-rotation",
            "CREW":     "edge-crew",
            "PAX_CNXN": "edge-pax",
        }.get(edge_type, "edge-rotation")

        # Highlight if both endpoints in cascade
        if trigger_id and (u == trigger_id or v == trigger_id or
                           u in affected_ids or v in affected_ids):
            edge_class += " edge-active"
        elif trigger_id:
            edge_class += " edge-dimmed"

        elements.append({
            "data": {
                "source":    u,
                "target":    v,
                "edge_type": edge_type,
                "slack_min": slack,
                "vuln":      vuln,
                "label":     edge_data.get("label", ""),
            },
            "classes": edge_class,
        })

    return elements


def build_cyto_stylesheet() -> list:
    """
    Full Cytoscape stylesheet for SILSILA network.
    Uses CSS-class selectors — matches the dark ops-center aesthetic.
    """
    return [
        # ── Base node ──────────────────────────────────────────────────────────
        {
            "selector": "node",
            "style": {
                "width":              "data(size)",
                "height":             "data(size)",
                "shape":              "roundrectangle",
                "background-color":   C["normal"],
                "border-width":       2,
                "border-color":       C["border"],
                "label":              "data(label)",
                "font-family":        "Barlow Condensed, sans-serif",
                "font-size":          10,
                "font-weight":        700,
                "color":              C["text_2"],
                "text-valign":        "center",
                "text-halign":        "center",
                "text-margin-y":      0,
                "text-outline-width": 2,
                "text-outline-color": C["bg_1"],
                "z-index":            10,
                "padding":            5,
                "transition-property":"background-color border-color",
                "transition-duration":"0.2s",
            },
        },
        # ── Node status classes ────────────────────────────────────────────────
        {
            "selector": "node.trigger",
            "style": {
                "background-color": C["cyan"],
                "border-color":     C["cyan"],
                "border-width":     3,
                "color":            C["bg_1"],
                "font-size":        12,
                "shape":            "roundrectangle",
                "width":            64,
                "height":           38,
                "z-index":          50,
            },
        },
        {
            "selector": "node.critical",
            "style": {
                "background-color": C["red"],
                "border-color":     C["red"],
                "color":            C["text_1"],
            },
        },
        {
            "selector": "node.delayed-high",
            "style": {
                "background-color": C["orange"],
                "border-color":     C["orange"],
                "color":            C["bg_1"],
            },
        },
        {
            "selector": "node.delayed",
            "style": {
                "background-color": C["gold"],
                "border-color":     C["gold"],
                "color":            C["bg_1"],
            },
        },
        {
            "selector": "node.landed",
            "style": {
                "background-color": C["landed"],
                "border-color":     "#2A7A5A",
            },
        },
        {
            "selector": "node.recovered",
            "style": {
                "background-color": C["recovered"],
                "border-color":     C["teal"],
            },
        },
        {
            "selector": "node.cancelled",
            "style": {
                "background-color": C["cancelled"],
                "border-color":     "#8A2A3A",
                "opacity":          0.5,
            },
        },
        # ── Hover / selected ──────────────────────────────────────────────────
        {
            "selector": "node:selected",
            "style": {
                "border-width":     4,
                "border-color":     C["text_1"],
                "overlay-opacity":  0.08,
                "overlay-color":    C["text_1"],
            },
        },
        {
            "selector": "node:active",
            "style": {"overlay-opacity": 0.1},
        },
        # ── Base edge ──────────────────────────────────────────────────────────
        {
            "selector": "edge",
            "style": {
                "width":               1.8,
                "opacity":             0.42,
                "line-color":          C["border"],
                "target-arrow-shape":  "triangle",
                "target-arrow-color":  C["border"],
                "arrow-scale":         0.95,
                "curve-style":         "bezier",
                "control-point-step-size": 40,
                "transition-property": "opacity line-color",
                "transition-duration": "0.2s",
            },
        },
        # ── Edge type classes ──────────────────────────────────────────────────
        {
            "selector": "edge.edge-rotation",
            "style": {
                "line-color":         C["cyan"],
                "target-arrow-color": C["cyan"],
                "line-style":         "solid",
            },
        },
        {
            "selector": "edge.edge-crew",
            "style": {
                "line-color":         C["teal"],
                "target-arrow-color": C["teal"],
                "line-style":         "dotted",
            },
        },
        {
            "selector": "edge.edge-pax",
            "style": {
                "line-color":         C["gold"],
                "target-arrow-color": C["gold"],
                "line-style":         "dashed",
                "line-dash-pattern":  [6, 4],
            },
        },
        # ── Active (cascade-highlighted) edges ────────────────────────────────
        {
            "selector": "edge.edge-active",
            "style": {
                "opacity":  1.0,
                "width":    2.8,
                "z-index":  30,
            },
        },
        {
            "selector": "edge.edge-dimmed",
            "style": {
                "opacity": 0.12,
                "width":   1.2,
            },
        },
        # ── Edge hover ────────────────────────────────────────────────────────
        {
            "selector": "edge:selected",
            "style": {
                "opacity":      1.0,
                "width":        3,
                "overlay-opacity": 0.06,
            },
        },
    ]
