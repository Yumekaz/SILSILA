"""
layout.py
---------
Defines the full Dash application layout.

Structure:
  Header  — branding, live clock, system status
  Left    — control panel (flight select, delay slider, trigger)
  Center  — NetworkX graph rendered via Plotly
  Right   — cascade event log + aggregate metrics
  Bottom  — Gantt timeline (original vs cascaded schedule)
"""

from dash import dcc, html
import plotly.graph_objects as go


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

def build_header() -> html.Div:
    return html.Div(className="app-header", children=[
        html.Div(className="header-brand", children=[
            html.Div(className="brand-title", children=[
                html.Span("QR"), " CASCADE SIM"
            ]),
            html.Div("HAMAD INTL · DOH/OTHH · PHASE 1", className="brand-sub"),
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
                html.Div("SYNTHETIC · OTHH", className="ind-value",
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
            html.Span("PHASE 1", className="panel-badge"),
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

def build_network_panel() -> html.Div:
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
                                 "background": "rgba(232,160,32,0.07)"}),
            ]),
        ]),
        html.Div(className="graph-container", children=[
            dcc.Graph(
                id="network-graph",
                figure=empty_network_fig(),
                config={"displayModeBar": False, "scrollZoom": True},
                style={"height": "100%", "width": "100%"},
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


# ─── Root Layout ──────────────────────────────────────────────────────────────

def build_layout(flight_options: list) -> html.Div:
    return html.Div([
        build_header(),
        html.Div(className="main-grid", children=[
            build_control_panel(flight_options),
            build_network_panel(),
            build_cascade_log_panel(),
        ]),
        build_gantt_panel(),

        # Hidden stores for state
        dcc.Store(id="cascade-result-store"),
        dcc.Store(id="schedule-store"),
    ])
