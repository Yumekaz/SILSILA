"""
layout.py
---------
Defines the full Dash application layout.

Structure:
  Header  — branding, live clock, system status
  Left    — control panel (flight select, delay slider, trigger)
  Center  — Cytoscape.js network graph (smooth zoom/pan)
  Right   — cascade event log + aggregate metrics
  Bottom  — Gantt timeline (original vs cascaded schedule)
"""

from dash import dcc, html
import dash_cytoscape as cyto
import plotly.graph_objects as go
from engine.config import MC_SCENARIOS


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _label(text: str) -> html.Div:
    return html.Div(text, className="control-label")



def _status_color(status: str) -> str:
    status = (status or "").upper()
    if status in {"NOMINAL", "HIGH", "LIVE"}:
        return "#75E0C0"
    if status in {"PARTIAL", "MEDIUM", "HYBRID", "RECOMMENDED", "REVIEWED"}:
        return "#E6C78E"
    if status in {"DEGRADED", "LOW", "OVERRIDDEN", "FALLBACK"}:
        return "#F3A074"
    if status in {"FAILED", "ACCEPTED"}:
        return "#FF7A86"
    return "#82768A"


def _display_data_source_label(source_label: str) -> str:
    normalized = (source_label or "").strip().upper()
    if not normalized:
        return "UNKNOWN SOURCE"
    if "HYBRID" in normalized:
        return "PUBLIC + SYNTHETIC"
    if normalized.startswith("OPENSKY"):
        return "PUBLIC ARRIVALS"
    if "SYNTHETIC" in normalized:
        return "SYNTHETIC SCHEDULE"
    return normalized


def _display_data_mode_label(mode_label: str) -> str:
    normalized = (mode_label or "").strip().upper()
    return {
        "LIVE": "LIVE MODE",
        "HYBRID": "HYBRID MODE",
        "FALLBACK": "FALLBACK MODE",
    }.get(normalized, normalized or "UNKNOWN MODE")


def _status_badge_style(status: str) -> dict:
    color = _status_color(status)
    return {
        "color": color,
        "borderColor": color,
        "background": "rgba(28, 24, 38, 0.88)",
    }



def empty_network_fig() -> go.Figure:
    """Blank network canvas — replaced by callback."""
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        xaxis=dict(visible=False, showgrid=False, zeroline=False),
        yaxis=dict(visible=False, showgrid=False, zeroline=False),
    )
    return fig



def empty_gantt_fig() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=120, r=20, t=10, b=40),
        font=dict(family="JetBrains Mono", color="#82768A", size=11),
        xaxis=dict(
            showgrid=True, gridcolor="rgba(59,45,73,0.7)", zeroline=False,
            tickfont=dict(size=10), color="#82768A"
        ),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=10)),
    )
    return fig


# ─── Header ───────────────────────────────────────────────────────────────────

def build_header(system_status_label: str, data_source_label: str, data_health_label: str, data_mode_label: str) -> html.Div:
    system_status_color = _status_color(system_status_label)
    data_health_color = _status_color(data_health_label)
    data_mode_color = _status_color(data_mode_label)
    return html.Div(className="app-header", children=[
        html.Div(className="header-brand", children=[
            html.Div(className="brand-title", children=[
                html.Span("SIL"), "SILA"
            ]),
            html.Div("DOHA NETWORK CONTROL · 24 / 7", className="brand-sub"),
        ]),
        html.Div(className="header-indicators", children=[
            html.Div(className="indicator", children=[
                html.Div("SYSTEM", className="ind-label"),
                html.Div([
                    html.Span(className="status-dot", style={"background": system_status_color, "boxShadow": f"0 0 8px {system_status_color}"}),
                    html.Span(system_status_label, style={"color": system_status_color,
                                                          "fontFamily": "JetBrains Mono",
                                                          "fontSize": "13px",
                                                          "fontWeight": "600"})
                ]),
            ]),
            html.Div(className="indicator", children=[
                html.Div("DATA HEALTH", className="ind-label"),
                html.Div(data_health_label, className="ind-value", style={"color": data_health_color}),
            ]),
            html.Div(className="indicator", children=[
                html.Div("DATA SOURCE", className="ind-label"),
                html.Div(_display_data_source_label(data_source_label), className="ind-value", style={"fontSize": "11px"}),
            ]),
            html.Div(className="indicator", children=[
                html.Div("OPS MODE", className="ind-label"),
                html.Div(_display_data_mode_label(data_mode_label), className="ind-value", style={"fontSize": "11px", "color": data_mode_color}),
            ]),
            html.Div(className="indicator", children=[
                html.Div("LOCAL TIME (AST)", className="ind-label"),
                html.Div("—:—", id="live-clock", className="ind-value"),
            ]),
        ]),
        dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
    ])


# ─── Control Panel (Left) ─────────────────────────────────────────────────────

def build_control_panel(flight_options: list, data_mode_label: str) -> html.Div:
    return html.Div(className="panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("SCENARIO BRIEF", className="panel-title"),
            html.Span((data_mode_label or "LOCAL").upper(), className="panel-badge", style=_status_badge_style(data_mode_label)),
        ]),
        html.Div(className="panel-body", children=[

            html.Div(className="control-section", children=[
                _label("WATCHLIST FLIGHT"),
                dcc.Dropdown(
                    id="flight-select",
                    options=flight_options,
                    value=flight_options[0]["value"] if flight_options else None,
                    clearable=False,
                    searchable=True,
                    style={
                        "backgroundColor": "#1C1826",
                        "borderColor":     "#3B2D49",
                        "color":           "#F6F0EB",
                        "fontFamily":      "JetBrains Mono",
                        "fontSize":        "13px",
                    }
                ),
                html.Div(id="selected-flight-card"),
            ]),

            html.Div(className="divider"),

            html.Div(className="control-section", children=[
                _label("DISRUPTION WINDOW"),
                html.Div("30 min", id="delay-display", className="delay-display"),
                dcc.Slider(
                    id="delay-slider",
                    min=5, max=240, step=5, value=30,
                    marks={
                        5:   {"label": "5m",   "style": {"color": "#82768A", "fontSize": "9px"}},
                        60:  {"label": "1h",   "style": {"color": "#82768A", "fontSize": "9px"}},
                        120: {"label": "2h",   "style": {"color": "#E6C78E", "fontSize": "9px"}},
                        180: {"label": "3h",   "style": {"color": "#F3A074", "fontSize": "9px"}},
                        240: {"label": "4h",   "style": {"color": "#FF7A86", "fontSize": "9px"}},
                    },
                    tooltip={"always_visible": False},
                ),
            ]),

            html.Div(className="divider"),

            html.Button(
                "▶  START SCENARIO",
                id="trigger-btn",
                className="trigger-btn",
                n_clicks=0,
            ),
            html.Button(
                "↺  CLEAR BRIEF",
                id="reset-btn",
                className="reset-btn",
                n_clicks=0,
            ),

            html.Div(className="divider"),
            html.Div(className="control-helper-card", children=[
                html.Div("FLIGHT DESK RUNBOOK", className="control-label"),
                html.Div("1. Choose a live arrival", className="control-helper-line"),
                html.Div("2. Model the network ripple", className="control-helper-line"),
                html.Div("3. Compare recovery moves", className="control-helper-line"),
                html.Div("4. Approve the cleanest landing", className="control-helper-line"),
            ]),
        ]),
    ])


# ─── Center: Network Graph ────────────────────────────────────────────────────

def build_network_panel(initial_elements: list | None = None, initial_stylesheet: list | None = None) -> html.Div:
    has_graph = bool(initial_elements)
    return html.Div(className="panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("NETWORK LENS · DOH HUB", className="panel-title"),
            html.Div(className="panel-header-actions", children=[
                html.Span("▸ ROTATION", className="tag",
                          style={"color": "#D0A7D9", "borderColor": "#765A7E",
                                 "background": "rgba(208,167,217,0.10)", "marginRight": "6px"}),
                html.Span("▸ CREW", className="tag",
                          style={"color": "#75E0C0", "borderColor": "#75E0C0",
                                 "background": "rgba(117,224,192,0.10)", "marginRight": "6px"}),
                html.Span("▸ PAX CNX", className="tag",
                          style={"color": "#E6C78E", "borderColor": "#8E7045",
                                 "background": "rgba(230,199,142,0.10)", "marginRight": "10px"}),
                html.Span(id="cyto-node-info", style={
                    "fontFamily": "JetBrains Mono", "fontSize": "10px",
                    "color": "#82768A", "letterSpacing": "0.05em"
                }),
            ]),
        ]),
        html.Div(className="graph-container", children=[
            html.Div(className="network-corner network-corner-tl", children=[html.Span("N", className="network-compass"), html.Span("LIVE / DOH", className="network-coord")]),
            html.Div(className="network-corner network-corner-tr", children=[html.Span("FLIGHT FIELD", className="network-coord"), html.Span("24H", className="network-time")]),
            html.Div(className="network-map-label", children=[html.Span("HUB / 01", className="network-map-kicker"), html.Span("NETWORK PULSE", className="network-map-title")]),
            html.Div(className="network-map-footer", children=[html.Span("DRAG TO PAN", className="network-coord"), html.Span("SCROLL TO ZOOM", className="network-coord"), html.Span("12 ACTIVE LINKS", className="network-coord")]),
            html.Div(
                id="graph-empty-state",
                className="graph-empty-state",
                style={"display": "none" if has_graph else "flex"},
                children=[
                    html.Div(className="graph-empty-card", children=[
                        html.Div("MAP IS READY · NETWORK STANDBY", className="graph-empty-title"),
                        html.Div(
                            "Choose a watchlist flight and start a scenario to reveal the ripple across aircraft, crew, and connections.",
                            className="graph-empty-body",
                        ),
                        html.Div(
                            "Every link is a decision surface. Follow the next departure at risk.",
                            className="graph-empty-caption",
                        ),
                    ]),
                ],
            ),
            cyto.Cytoscape(
                id="network-graph",
                layout={"name": "preset"},
                style={"height": "100%", "width": "100%", "background": "#100D15"},
                elements=initial_elements or [],
                stylesheet=initial_stylesheet or [],
                userZoomingEnabled=True,
                userPanningEnabled=True,
                minZoom=0.2,
                maxZoom=3.0,
                responsive=True,
            ),
        ]),
    ])


# ─── Right: Cascade Log ───────────────────────────────────────────────────────

def build_cascade_log_panel() -> html.Div:
    return html.Div(className="panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("IMPACT RADAR", className="panel-title"),
            html.Span("0 AFFECTED", id="affected-count", className="panel-badge"),
        ]),
        html.Div(className="panel-body cascade-panel-body", children=[
            html.Div(id="summary-metrics"),
            html.Div(className="cascade-feed-head", children=[
                html.Div("SIGNAL FEED", className="control-label"),
                html.Div("Highest-risk movements first.", className="cascade-feed-copy"),
            ]),
            html.Div(className="cascade-log-scroll", id="cascade-log", children=[
                html.Div(className="log-empty", children=[
                    html.Div("◌", className="icon"),
                    html.Div("AWAITING INPUT"),
                    html.Div("Your flight brief is loaded. Start a scenario to light up the impact radar.",
                             style={"opacity": "0.5", "textTransform": "none",
                                     "letterSpacing": "0"}),
                ])
            ]),
        ]),
    ])


# ─── Bottom: Gantt ────────────────────────────────────────────────────────────

def build_gantt_panel() -> html.Div:
    return html.Div(className="bottom-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("SCHEDULE PULSE · PLAN vs REALITY", className="panel-title"),
            html.Span("TIME HORIZON", className="panel-badge"),
        ]),
        html.Div(className="gantt-container", children=[
            dcc.Graph(
                id="gantt-chart",
                figure=empty_gantt_fig(),
                config={"displayModeBar": False},
                style={"height": "200px"},
            ),
        ]),
    ])



def build_recovery_panel() -> html.Div:
    return html.Div(className="recovery-panel", id="recovery-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("RECOVERY DESK", className="panel-title"),
            html.Div(className="panel-header-actions", children=[
                html.Span("DECISION QUEUE", className="panel-badge", style={"marginRight": "6px"}),
                html.Span("AWAITING CASCADE", className="panel-badge status-pill status-awaiting", id="recovery-status-badge"),
            ]),
        ]),
        html.Div(
            id="recovery-cards",
            className="recovery-cards-empty",
            children=[
                html.Div(className="log-empty", children=[
                    html.Div("◈", className="icon"),
                    html.Div("AWAITING A SCENARIO"),
                    html.Div("Start a scenario to generate recovery moves.",
                             style={"opacity": "0.5", "textTransform": "none", "letterSpacing": "0"}),
                ])
            ]
        ),
        html.Div(id="optimizer-summary", className="mc-network-stats"),
        html.Div(id="recovery-comparison-strip", className="comparison-strip", children=[
            html.Div(className="comparison-empty", children="No recovery option selected yet.")
        ]),
        html.Div(className="workflow-toolbar", children=[
            html.Div(className="workflow-status-block", children=[
                html.Div("OPERATOR DECISION", className="control-label"),
                html.Div("AWAITING CASCADE", id="operator-state-badge", className="workflow-state-badge status-pill status-awaiting"),
            ]),
            html.Div(className="workflow-actions", children=[
                html.Button("MARK REVIEWED", id="mark-reviewed-btn", className="workflow-btn", n_clicks=0, disabled=True),
                html.Button("COMMIT RECOVERY", id="accept-plan-btn", className="workflow-btn workflow-btn-accept", n_clicks=0, disabled=True),
                html.Button("OPEN OVERRIDE", id="override-plan-btn", className="workflow-btn workflow-btn-override", n_clicks=0, disabled=True),
            ]),
            html.Div(
                "Run a simulation to create an auditable scenario.",
                id="workflow-activity-note",
                className="workflow-note",
            ),
        ]),
    ])



def build_monte_carlo_panel() -> html.Div:
    return html.Div(className="mc-panel", id="mc-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("RISK STUDIO · MONTE CARLO", className="panel-title"),
            html.Div(className="panel-header-actions", children=[
                html.Span("DECISION SCIENCE", className="panel-badge", style={"marginRight": "6px"}),
                html.Span(f"{MC_SCENARIOS} SCENARIOS", className="panel-badge", style={"marginRight": "6px"}),
                html.Button("▶  RUN MONTE CARLO", id="mc-run-btn", className="mc-run-btn", n_clicks=0),
                html.Button("⬇  EXPORT PDF", id="pdf-export-btn", className="mc-export-btn", n_clicks=0, disabled=True),
                dcc.Download(id="pdf-download"),
            ]),
        ]),
        html.Div(id="mc-status-bar", className="mc-status-bar", children=[
            html.Div(className="log-empty", style={"height": "60px"}, children=[
                html.Div("◈", className="icon"),
                html.Div(f"MONTE CARLO READY — click RUN to simulate {MC_SCENARIOS} scenarios",
                         style={"textTransform": "none", "letterSpacing": "0"}),
            ])
        ]),
        html.Div(className="mc-charts-grid", id="mc-charts", children=[]),
        html.Div(id="mc-network-stats", className="mc-network-stats"),
    ])



def build_sensitivity_panel() -> html.Div:
    return html.Div(className="mc-panel", id="sensitivity-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("SENSITIVITY LAB · TURNAROUND", className="panel-title"),
            html.Div(className="panel-header-actions", children=[
                html.Span("SENSITIVITY", className="panel-badge", style={"marginRight": "6px"}),
                html.Button("▶  RUN SENSITIVITY", id="sensitivity-run-btn", className="mc-run-btn", n_clicks=0),
            ]),
        ]),
        html.Div(id="sensitivity-status-bar", className="mc-status-bar", children=[
            html.Div(className="log-empty", style={"height": "60px"}, children=[
                html.Div("◈", className="icon"),
                html.Div("SENSITIVITY READY — compare 35/45/55/65 minute turnaround assumptions",
                         style={"textTransform": "none", "letterSpacing": "0"}),
            ]),
        ]),
        html.Div(className="mc-charts-grid", children=[
            html.Div(className="mc-chart-cell mc-chart-wide", children=[
                dcc.Graph(
                    id="sensitivity-chart",
                    figure=empty_gantt_fig(),
                    config={"displayModeBar": False},
                    style={"height": "240px"},
                ),
            ]),
        ]),
        html.Div(id="sensitivity-summary", className="mc-network-stats"),
    ])


# ─── Root Layout ──────────────────────────────────────────────────────────────

def build_layout(
    flight_options: list,
    system_status_label: str,
    data_source_label: str,
    data_health_label: str,
    data_mode_label: str,
    initial_graph_elements: list | None = None,
    initial_graph_stylesheet: list | None = None,
) -> html.Div:
    return html.Div([
        build_header(system_status_label, data_source_label, data_health_label, data_mode_label),
        html.Section(className="command-hero", children=[
            html.Div(className="hero-copy", children=[
                html.Div("01 / FLIGHT DESK · DOHA HUB", className="hero-eyebrow"),
                html.H1("Move the hub\nbefore the delay.", className="hero-title"),
                html.P("Read the ripple, protect the next departure, and move from signal to recovery without leaving the room.", className="hero-description"),
                html.Div(className="hero-metrics", children=[
                    html.Div(className="hero-metric", children=[
                        html.Div("NETWORK", className="hero-metric-label"),
                        html.Div([html.Span("32", className="hero-metric-value"), html.Span(" NODES", className="hero-metric-unit")]),
                    ]),
                    html.Div(className="hero-metric", children=[
                        html.Div("DECISION LATENCY", className="hero-metric-label"),
                        html.Div([html.Span("04", className="hero-metric-value"), html.Span(" MIN", className="hero-metric-unit")]),
                    ]),
                    html.Div(className="hero-metric", children=[
                        html.Div("MODEL CONFIDENCE", className="hero-metric-label"),
                        html.Div([html.Span("98.2", className="hero-metric-value"), html.Span(" %", className="hero-metric-unit")]),
                    ]),
                ]),
                html.Div(className="hero-actions", children=[
                    html.A("OPEN IMPACT CONSOLE  ↓", href="#network-graph", className="hero-action-primary"),
                    html.A("HOW IT WORKS  ↗", href="#recovery-panel", className="hero-action-secondary"),
                ]),
            ]),
            html.Div(className="hero-signal", children=[
                html.Div(className="signal-orbit", children=[html.Span("LIVE", className="orbit-label"), html.Div(className="orbit-ring ring-one"), html.Div(className="orbit-ring ring-two")]),
                html.Div(className="hero-signal-copy", children=[
                    html.Div("HUB WINDOW · AST", className="hero-signal-kicker"),
                    html.Div("06:28 — 08:40", className="hero-signal-title"),
                    html.Div([html.Span("DOH", className="hero-route-node"), html.Span("↔", className="hero-route-arrow"), html.Span("32 FLIGHTS", className="hero-route-node")], className="hero-signal-note"),
                ]),
            ]),
            html.Canvas(id="hero-scene", className="hero-scene", **{"aria-hidden": "true"}),
            html.Div("SCROLL TO EXPLORE  ↓", className="hero-scroll-cue"),
        ]),
        html.Div(className="ops-ticker", children=[
            html.Div("LIVE ROUTE INTELLIGENCE", className="ops-ticker-lead"),
            html.Div("DOH  →  32 DEPARTURES", className="ops-ticker-item"),
            html.Div("NEXT DECISION  06:28 AST", className="ops-ticker-item"),
            html.Div("MODEL HEALTH  98.2%", className="ops-ticker-item ops-ticker-good"),
            html.Div("◉  SYSTEM NOMINAL", className="ops-ticker-item ops-ticker-good"),
        ]),
        html.Nav(className="section-nav", children=[
            html.Div("OPERATION / 01", className="section-nav-label"),
            html.A("01 · BRIEF", href="#flight-select", className="section-nav-link active"),
            html.A("02 · LENS", href="#network-graph", className="section-nav-link"),
            html.A("03 · RADAR", href="#cascade-log", className="section-nav-link"),
            html.A("04 · DESK", href="#recovery-panel", className="section-nav-link"),
            html.A("05 · STUDIO", href="#mc-panel", className="section-nav-link"),
        ]),
        html.Div(className="main-grid", children=[
            build_control_panel(flight_options, data_mode_label),
            build_network_panel(initial_graph_elements, initial_graph_stylesheet),
            build_cascade_log_panel(),
        ]),
        build_recovery_panel(),
        build_gantt_panel(),
        build_monte_carlo_panel(),
        build_sensitivity_panel(),
        dcc.Store(id="cascade-result-store"),
        dcc.Store(id="schedule-store"),
        dcc.Store(id="recovery-options-store"),
        dcc.Store(id="selected-recovery-store"),
        dcc.Store(id="mc-result-store"),
        dcc.Store(id="scenario-id-store"),
        dcc.Store(id="operator-state-store"),
    ])
