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


def empty_network_fig() -> go.Figure:
    """Blank network canvas — replaced by callback."""
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor ="rgba(0,0,0,0)",
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
        plot_bgcolor ="rgba(0,0,0,0)",
        margin=dict(l=120, r=20, t=10, b=40),
        font=dict(family="JetBrains Mono", color="#8CA0C0", size=11),
        xaxis=dict(
            showgrid=True, gridcolor="rgba(28,45,72,0.8)", zeroline=False,
            tickfont=dict(size=10), color="#4A6080"
        ),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=10)),
    )
    return fig


# ─── Header ───────────────────────────────────────────────────────────────────

def build_header(data_source_label: str) -> html.Div:
    return html.Div(className="app-header", children=[
        html.Div(className="header-brand", children=[
            html.Div(className="brand-title", children=[
                html.Span("SIL"), "SILA"
            ]),
            html.Div("HAMAD INTL · DOH/OTHH · OPS COMMAND", className="brand-sub"),
        ]),
        html.Div(className="header-indicators", children=[
            html.Div(className="indicator", children=[
                html.Div("SYSTEM", className="ind-label"),
                html.Div([
                    html.Span(className="status-dot"),
                    html.Span("NOMINAL", style={"color": "#00D4A0",
                                                "fontFamily": "JetBrains Mono",
                                                "fontSize": "13px",
                                                "fontWeight": "600"})
                ]),
            ]),
            html.Div(className="indicator", children=[
                html.Div("LOCAL TIME (AST)", className="ind-label"),
                html.Div("—:—", id="live-clock", className="ind-value"),
            ]),
            html.Div(className="indicator", children=[
                html.Div("DATA SOURCE", className="ind-label"),
                html.Div(data_source_label, className="ind-value",
                         style={"fontSize": "11px"}),
            ]),
        ]),
        dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
    ])


# ─── Control Panel (Left) ─────────────────────────────────────────────────────

def build_control_panel(flight_options: list) -> html.Div:
    return html.Div(className="panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("DISRUPTION INPUT", className="panel-title"),
            html.Span("LIVE", className="panel-badge"),
        ]),
        html.Div(className="panel-body", children=[

            # ── Flight selector ──────────────────────────────────────────────
            html.Div(className="control-section", children=[
                _label("SELECT TRIGGER FLIGHT"),
                dcc.Dropdown(
                    id="flight-select",
                    options=flight_options,
                    value=flight_options[0]["value"] if flight_options else None,
                    clearable=False,
                    searchable=True,
                    style={
                        "backgroundColor": "#111B30",
                        "borderColor":     "#1C2D48",
                        "color":           "#E4EBF7",
                        "fontFamily":      "JetBrains Mono",
                        "fontSize":        "13px",
                    }
                ),
                html.Div(id="selected-flight-card"),
            ]),

            html.Div(className="divider"),

            # ── Delay slider ─────────────────────────────────────────────────
            html.Div(className="control-section", children=[
                _label("DELAY MAGNITUDE"),
                html.Div("30 min", id="delay-display", className="delay-display"),
                dcc.Slider(
                    id="delay-slider",
                    min=5, max=240, step=5, value=30,
                    marks={
                        5:   {"label": "5m",   "style": {"color": "#4A6080", "fontSize": "9px"}},
                        60:  {"label": "1h",   "style": {"color": "#4A6080", "fontSize": "9px"}},
                        120: {"label": "2h",   "style": {"color": "#E8A020", "fontSize": "9px"}},
                        180: {"label": "3h",   "style": {"color": "#FF6B35", "fontSize": "9px"}},
                        240: {"label": "4h",   "style": {"color": "#FF3D5A", "fontSize": "9px"}},
                    },
                    tooltip={"always_visible": False},
                ),
            ]),

            html.Div(className="divider"),

            # ── Action buttons ───────────────────────────────────────────────
            html.Button(
                "▶  SIMULATE CASCADE",
                id="trigger-btn",
                className="trigger-btn",
                n_clicks=0,
            ),
            html.Button(
                "↺  RESET",
                id="reset-btn",
                className="reset-btn",
                n_clicks=0,
            ),

            html.Div(className="divider"),

            # ── Summary metrics (post-cascade) ───────────────────────────────
            html.Div(id="summary-metrics"),
        ]),
    ])


# ─── Center: Network Graph ────────────────────────────────────────────────────

def build_network_panel(initial_elements: list | None = None, initial_stylesheet: list | None = None) -> html.Div:
    has_graph = bool(initial_elements)
    return html.Div(className="panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("DOH HUB DEPENDENCY GRAPH", className="panel-title"),
            html.Div([
                html.Span("▸ ROTATION", className="tag",
                          style={"color": "#00C8FF", "borderColor": "#006A87",
                                 "background": "rgba(0,200,255,0.07)", "marginRight": "6px"}),
                html.Span("▸ CREW", className="tag",
                          style={"color": "#00D4A0", "borderColor": "#00D4A0",
                                 "background": "rgba(0,212,160,0.07)", "marginRight": "6px"}),
                html.Span("▸ PAX CNX", className="tag",
                          style={"color": "#E8A020", "borderColor": "#9B6B14",
                                 "background": "rgba(232,160,32,0.07)", "marginRight": "10px"}),
                # Node info tooltip (populated on click)
                html.Span(id="cyto-node-info", style={
                    "fontFamily": "JetBrains Mono", "fontSize": "10px",
                    "color": "#4A6080", "letterSpacing": "0.05em"
                }),
            ]),
        ]),
        html.Div(className="graph-container", children=[
            html.Div(
                id="graph-empty-state",
                className="graph-empty-state",
                style={"display": "none" if has_graph else "flex"},
                children=[
                    html.Div(className="graph-empty-card", children=[
                        html.Div("NETWORK STANDBY", className="graph-empty-title"),
                        html.Div(
                            "Select an inbound trigger flight and click SIMULATE CASCADE to render the impacted dependency paths.",
                            className="graph-empty-body",
                        ),
                        html.Div(
                            "The underlying hub network changes by flight selection, but highlighted links only appear after a simulated trigger.",
                            className="graph-empty-caption",
                        ),
                    ]),
                ],
            ),
            cyto.Cytoscape(
                id="network-graph",
                layout={"name": "preset"},
                style={"height": "100%", "width": "100%",
                       "background": "#06090F"},
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
            html.Span("CASCADE LOG", className="panel-title"),
            html.Span("0 AFFECTED", id="affected-count", className="panel-badge"),
        ]),
        html.Div(className="panel-body", id="cascade-log", children=[
            html.Div(className="log-empty", children=[
                html.Div("◌", className="icon"),
                html.Div("AWAITING INPUT"),
                html.Div("Select a flight and set delay",
                         style={"opacity": "0.5", "textTransform": "none",
                                "letterSpacing": "0"}),
            ])
        ]),
    ])


# ─── Bottom: Gantt ────────────────────────────────────────────────────────────

def build_gantt_panel() -> html.Div:
    return html.Div(className="bottom-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("ROTATION TIMELINE · SCHEDULED vs CASCADED", className="panel-title"),
            html.Span("GANTT", className="panel-badge"),
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
    """Phase 2: Recovery options comparison panel — shown after cascade simulation."""
    return html.Div(className="recovery-panel", id="recovery-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("RECOVERY OPTIONS", className="panel-title"),
            html.Div([
                html.Span("RECOVERY", className="panel-badge",
                          style={"marginRight": "6px"}),
                html.Span("AWAITING CASCADE", className="panel-badge",
                          id="recovery-status-badge"),
            ]),
        ]),
        html.Div(
            id="recovery-cards",
            className="recovery-cards-empty",
            children=[
                html.Div(className="log-empty", children=[
                    html.Div("◈", className="icon"),
                    html.Div("RUN SIMULATION FIRST"),
                    html.Div("Recovery options appear after cascade analysis",
                             style={"opacity": "0.5", "textTransform": "none",
                                    "letterSpacing": "0"}),
                ])
            ]
        ),
        html.Div(id="optimizer-summary", className="mc-network-stats"),
    ])


def build_monte_carlo_panel() -> html.Div:
    """Phase 3: Monte Carlo risk panel with heatmap and distribution charts."""
    return html.Div(className="mc-panel", id="mc-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("MONTE CARLO RISK ANALYSIS", className="panel-title"),
            html.Div([
                html.Span("RISK LAB", className="panel-badge", style={"marginRight": "6px"}),
                html.Span(f"{MC_SCENARIOS} SCENARIOS", className="panel-badge",
                          style={"marginRight": "6px"}),
                html.Button(
                    "▶  RUN MONTE CARLO",
                    id="mc-run-btn",
                    className="mc-run-btn",
                    n_clicks=0,
                ),
                html.Button(
                    "⬇  EXPORT PDF",
                    id="pdf-export-btn",
                    className="mc-export-btn",
                    n_clicks=0,
                ),
                dcc.Download(id="pdf-download"),
            ]),
        ]),
        # Progress / status bar
        html.Div(id="mc-status-bar", className="mc-status-bar", children=[
            html.Div(className="log-empty", style={"height": "60px"}, children=[
                html.Div("◈", className="icon"),
                html.Div(f"MONTE CARLO READY — click RUN to simulate {MC_SCENARIOS} scenarios",
                         style={"textTransform": "none", "letterSpacing": "0"}),
            ])
        ]),
        # Charts row
        html.Div(className="mc-charts-grid", id="mc-charts", children=[]),
        # Network summary stats
        html.Div(id="mc-network-stats", className="mc-network-stats"),
    ])


def build_sensitivity_panel() -> html.Div:
    """Turnaround sensitivity analysis panel."""
    return html.Div(className="mc-panel", id="sensitivity-panel", children=[
        html.Div(className="panel-header", children=[
            html.Span("TURNAROUND SENSITIVITY ANALYSIS", className="panel-title"),
            html.Div([
                html.Span("SENSITIVITY", className="panel-badge", style={"marginRight": "6px"}),
                html.Button(
                    "▶  RUN SENSITIVITY",
                    id="sensitivity-run-btn",
                    className="mc-run-btn",
                    n_clicks=0,
                ),
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
    data_source_label: str,
    initial_graph_elements: list | None = None,
    initial_graph_stylesheet: list | None = None,
) -> html.Div:
    return html.Div([
        build_header(data_source_label),
        html.Div(className="main-grid", children=[
            build_control_panel(flight_options),
            build_network_panel(initial_graph_elements, initial_graph_stylesheet),
            build_cascade_log_panel(),
        ]),
        build_recovery_panel(),
        build_gantt_panel(),
        build_monte_carlo_panel(),
        build_sensitivity_panel(),

        # Hidden stores
        dcc.Store(id="cascade-result-store"),
        dcc.Store(id="schedule-store"),
        dcc.Store(id="recovery-options-store"),
        dcc.Store(id="selected-recovery-store"),
        dcc.Store(id="mc-result-store"),
    ])
