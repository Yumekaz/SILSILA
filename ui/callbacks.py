"""
callbacks.py
------------
All Dash callback functions — the reactive layer between UI and engine.
Network graph now uses dash-cytoscape for smooth native zoom/pan.
"""

import json
from datetime import datetime, timezone
from dash import Input, Output, State, html
import plotly.graph_objects as go
import pandas as pd
import networkx as nx

from engine.cascade import run_cascade, cascaded_schedule
from engine.recovery import evaluate_all_recovery_options, RecoveryOption
from engine.cyto_graph import build_cyto_elements, build_cyto_stylesheet

# ── Color palette (matches CSS variables) ─────────────────────────────────────
COLORS = {
    "bg_0":    "#06090F",
    "bg_1":    "#0C1220",
    "bg_2":    "#111B30",
    "bg_3":    "#172039",
    "border":  "#1C2D48",
    "gold":    "#E8A020",
    "gold_dim":"#9B6B14",
    "cyan":    "#00C8FF",
    "cyan_dim":"#006A87",
    "teal":    "#00D4A0",
    "red":     "#FF3D5A",
    "orange":  "#FF6B35",
    "text_1":  "#E4EBF7",
    "text_2":  "#8CA0C0",
    "text_3":  "#4A6080",
    # Flight status
    "normal":   "#2A4A7A",
    "trigger":  "#00C8FF",
    "delayed":  "#E8A020",
    "delayed_h":"#FF6B35",
    "critical": "#FF3D5A",
    "landed":   "#2A5A4A",
}

FONT = dict(family="JetBrains Mono, monospace")


def register_callbacks(app, G, df):
    """Register all callbacks. Called from app.py after Dash is initialised."""

    # Pre-build stylesheet once — it doesn't change between cascades
    CYTO_STYLESHEET = build_cyto_stylesheet()

    # ── Live clock ─────────────────────────────────────────────────────────────
    @app.callback(
        Output("live-clock", "children"),
        Input("clock-interval", "n_intervals")
    )
    def update_clock(_):
        now = datetime.now(tz=timezone.utc)
        # AST = UTC+3
        ast_hour = (now.hour + 3) % 24
        return f"{ast_hour:02d}:{now.minute:02d}:{now.second:02d}"

    # ── Delay display ──────────────────────────────────────────────────────────
    @app.callback(
        Output("delay-display", "children"),
        Input("delay-slider", "value")
    )
    def update_delay_display(val):
        if val is None:
            return "— min"
        if val >= 60:
            h, m = divmod(val, 60)
            return [f"{h}h {m:02d}", html.Span(" min")]
        return [str(val), html.Span(" min")]

    # ── Selected flight info card ──────────────────────────────────────────────
    @app.callback(
        Output("selected-flight-card", "children"),
        Input("flight-select", "value")
    )
    def update_flight_card(flight_id):
        if not flight_id or flight_id not in G.nodes:
            return html.Div()
        d = G.nodes[flight_id]
        direction = d.get("direction", "")
        origin    = d.get("origin", "—")
        dest      = d.get("destination", "—")
        route     = f"{origin} → {dest}"

        ref_time = d.get("arr_actual" if direction == "inbound" else "dep_scheduled")
        time_str  = ref_time.strftime("%H:%M") if pd.notna(ref_time) else "—"

        return html.Div(className="flight-card", children=[
            html.Div([
                html.Span(flight_id, className="flight-card-route"),
                html.Span(" · ", style={"color": COLORS["text_3"]}),
                html.Span(
                    "INBOUND" if direction == "inbound" else "OUTBOUND",
                    className="tag tag-inbound" if direction == "inbound" else "tag tag-outbound",
                    style={"marginLeft": "4px", "verticalAlign": "middle"}
                ),
            ]),
            html.Div(
                f"{origin} → {dest}",
                style={"fontFamily": "JetBrains Mono", "fontSize": "12px",
                       "color": COLORS["text_2"], "marginTop": "4px"}
            ),
            html.Div(className="flight-card-meta", children=[
                html.Div(className="meta-item", children=[
                    html.Div("AIRCRAFT", className="meta-key"),
                    html.Div(d.get("aircraft_reg", "—"), className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("TYPE", className="meta-key"),
                    html.Div(d.get("aircraft_type", "—"), className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("PAX ONBOARD", className="meta-key"),
                    html.Div(f"{d.get('pax', 0):,}", className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("SCHED TIME", className="meta-key"),
                    html.Div(time_str, className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("SLACK", className="meta-key"),
                    html.Div(
                        f"{d.get('turnaround_slack_min', 0):.0f} min",
                        className="meta-val",
                        style={"color": COLORS["gold"] if d.get('turnaround_slack_min', 999) < 30 else COLORS["text_2"]}
                    ),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("CREW", className="meta-key"),
                    html.Div(d.get("crew_id", "—"), className="meta-val"),
                ]),
            ]),
        ])

    # ── Color extras for recovery ──────────────────────────────────────────────
    COLORS["recovered"]  = "#1A7A4A"
    COLORS["cancelled"]  = "#4A1A2A"

    # ── Main simulation callback ───────────────────────────────────────────────
    @app.callback(
        Output("cascade-result-store",   "data"),
        Output("network-graph",          "elements",    allow_duplicate=True),
        Output("network-graph",          "stylesheet",  allow_duplicate=True),
        Output("cascade-log",            "children"),
        Output("affected-count",         "children"),
        Output("gantt-chart",            "figure"),
        Output("summary-metrics",        "children"),
        Output("recovery-cards",         "children"),
        Output("recovery-status-badge",  "children"),
        Input("trigger-btn",  "n_clicks"),
        Input("reset-btn",    "n_clicks"),
        State("flight-select","value"),
        State("delay-slider", "value"),
        prevent_initial_call=True
    )
    def run_simulation(trigger_clicks, reset_clicks, flight_id, delay_min):
        from dash import ctx
        triggered = ctx.triggered_id

        empty_recovery = _empty_recovery_cards()

        if triggered == "reset-btn":
            return (
                None,
                [],
                [],
                _empty_log(),
                "0 AFFECTED",
                _build_gantt(df, None),
                html.Div(),
                empty_recovery,
                "AWAITING CASCADE",
            )

        if not flight_id or not delay_min:
            return (
                None,
                [],
                [],
                _empty_log(), "0 AFFECTED",
                _build_gantt(df, None),
                html.Div(),
                empty_recovery,
                "AWAITING CASCADE",
            )

        # ── Phase 1: Run cascade ───────────────────────────────────────────────
        result       = run_cascade(G, flight_id, float(delay_min))
        summary      = result.summary()
        df_cascaded  = cascaded_schedule(df, G, result)
        affected_ids = {e.flight_id for e in result.events}

        # ── Phase 2: Evaluate recovery options ─────────────────────────────────
        recovery_options = evaluate_all_recovery_options(G, df, result)

        return (
            json.dumps(summary),
            build_cyto_elements(G, df_cascaded, flight_id, affected_ids),
            CYTO_STYLESHEET,
            _build_cascade_log(result),
            f"{result.flights_affected} AFFECTED",
            _build_gantt(df_cascaded, result),
            _build_summary_metrics(result),
            _build_recovery_cards(recovery_options),
            f"{len([o for o in recovery_options if o.feasible])} OPTIONS READY",
        )

    # ── Apply selected recovery to Gantt + graph ───────────────────────────────
    @app.callback(
        Output("gantt-chart",             "figure",     allow_duplicate=True),
        Output("network-graph",           "elements",   allow_duplicate=True),
        Output("selected-recovery-store", "data"),
        Input({"type": "recovery-select-btn", "index": 0}, "n_clicks"),
        Input({"type": "recovery-select-btn", "index": 1}, "n_clicks"),
        Input({"type": "recovery-select-btn", "index": 2}, "n_clicks"),
        State("flight-select",  "value"),
        State("delay-slider",   "value"),
        prevent_initial_call=True
    )
    def apply_recovery(c0, c1, c2, flight_id, delay_min):
        from dash import ctx
        from dash.exceptions import PreventUpdate
        if not ctx.triggered_id or not flight_id or not delay_min:
            raise PreventUpdate

        triggered_idx = ctx.triggered_id.get("index", 0)
        result  = run_cascade(G, flight_id, float(delay_min))
        options = evaluate_all_recovery_options(G, df, result)

        if triggered_idx >= len(options):
            raise PreventUpdate

        selected = options[triggered_idx]
        if not selected.feasible or selected.df_recovered is None:
            raise PreventUpdate

        df_rec       = selected.df_recovered
        affected_ids = {e.flight_id for e in selected.residual_events}

        return (
            _build_gantt(df_rec, result, recovery_label=selected.label),
            build_cyto_elements(G, df_rec, flight_id, affected_ids),
            selected.strategy,
        )

    # ── Node click → show info in header ──────────────────────────────────────
    @app.callback(
        Output("cyto-node-info", "children"),
        Input("network-graph",   "tapNodeData"),
        prevent_initial_call=True
    )
    def show_node_info(node_data):
        if not node_data:
            return ""
        fid  = node_data.get("id", "")
        orig = node_data.get("origin", "")
        dest = node_data.get("destination", "")
        pax  = node_data.get("pax", 0)
        slk  = node_data.get("slack", 0)
        return f"{fid}  {orig}→{dest}  PAX {pax:,}  slack {slk:.0f}m"


# ── Figure builders ────────────────────────────────────────────────────────────

# _build_gantt defined below with recovery_label parameter


def _build_cascade_log(result) -> list:
    """Build the right-panel cascade event list."""
    if not result.events:
        return [html.Div(className="log-empty", children=[
            html.Div("◎", className="icon"),
            html.Div("NO CASCADE"),
            html.Div("Delay absorbed within existing slack",
                     style={"opacity": "0.5", "textTransform": "none"}),
        ])]

    items = []
    for event in result.events:
        delay_str = f"+{event.delay_min:.0f} min"
        path_str  = " → ".join(event.propagation_path)

        items.append(html.Div(
            className=f"cascade-item severity-{event.severity}",
            children=[
                html.Div(className="cascade-item-top", children=[
                    html.Span([
                        event.flight_id,
                        html.Span(event.edge_type,
                                  className=f"ci-type-tag {event.edge_type}"),
                    ], className="ci-flight"),
                    html.Span(delay_str,
                              className=f"ci-delay {event.severity}"),
                ]),
                html.Div([
                    html.Span(f"via {event.caused_by}", style={"marginRight": "8px"}),
                    html.Span(f"PAX: {event.pax_affected:,}"),
                    html.Span(f"  ${event.cost_usd:,.0f}",
                              style={"color": COLORS["text_3"]}),
                ], className="ci-meta"),
                html.Div(
                    path_str,
                    style={"fontFamily": "JetBrains Mono", "fontSize": "9px",
                           "color": COLORS["text_3"], "marginTop": "3px",
                           "whiteSpace": "nowrap", "overflow": "hidden",
                           "textOverflow": "ellipsis"}
                ),
            ]
        ))
    return items


def _build_summary_metrics(result) -> html.Div:
    s = result.summary()
    return html.Div([
        html.Div(className="metrics-row", children=[
            html.Div(className="metric-box gold", children=[
                html.Div("FLIGHTS HIT",  className="metric-key"),
                html.Div(s["flights_affected"], className="metric-val"),
            ]),
            html.Div(className="metric-box red", children=[
                html.Div("TOTAL DELAY",  className="metric-key"),
                html.Div(f"{s['total_delay_min']:.0f}m", className="metric-val"),
            ]),
        ]),
        html.Div(className="metrics-row", children=[
            html.Div(className="metric-box cyan", children=[
                html.Div("PAX AFFECTED", className="metric-key"),
                html.Div(f"{s['total_pax_affected']:,}", className="metric-val"),
            ]),
            html.Div(className="metric-box teal", children=[
                html.Div("EST. COST",    className="metric-key"),
                html.Div(f"${s['estimated_cost_usd']:,.0f}", className="metric-val",
                         style={"fontSize": "16px"}),
            ]),
        ]),
    ])


def _empty_log() -> list:
    return [html.Div(className="log-empty", children=[
        html.Div("◌", className="icon"),
        html.Div("AWAITING INPUT"),
        html.Div("Select a flight and set delay",
                 style={"opacity": "0.5", "textTransform": "none",
                        "letterSpacing": "0"}),
    ])]


# ── Recovery UI Builders ───────────────────────────────────────────────────────

def _empty_recovery_cards() -> list:
    return [html.Div(className="log-empty", children=[
        html.Div("◈", className="icon"),
        html.Div("RUN SIMULATION FIRST"),
        html.Div("Recovery options appear after cascade analysis",
                 style={"opacity": "0.5", "textTransform": "none", "letterSpacing": "0"}),
    ])]


def _build_recovery_cards(options: list) -> list:
    """Build side-by-side recovery option cards."""
    if not options:
        return _empty_recovery_cards()

    STRATEGY_COLORS = {
        "SWAP":   {"accent": "#00C8FF", "dim": "#006A87", "icon": "⇄"},
        "DELAY":  {"accent": "#E8A020", "dim": "#9B6B14", "icon": "⏱"},
        "CANCEL": {"accent": "#FF3D5A", "dim": "#7A1A2A", "icon": "✕"},
    }

    SCORE_LABEL = {
        (80, 100): ("RECOMMENDED", "#00D4A0"),
        (50, 80):  ("VIABLE",      "#E8A020"),
        (0, 50):   ("COSTLY",      "#FF6B35"),
    }

    def score_badge(score):
        for (lo, hi), (label, color) in SCORE_LABEL.items():
            if lo <= score <= hi:
                return label, color
        return "REVIEW", "#8CA0C0"

    cards = []
    for idx, opt in enumerate(options):
        sc      = STRATEGY_COLORS.get(opt.strategy, {"accent": "#8CA0C0", "dim": "#4A6080", "icon": "?"})
        s_label, s_color = score_badge(opt.score)

        if not opt.feasible:
            card = html.Div(className="recovery-card recovery-card-infeasible", children=[
                html.Div(className="rc-header", children=[
                    html.Span(sc["icon"], className="rc-icon",
                              style={"color": COLORS["text_3"]}),
                    html.Span(opt.label, className="rc-title",
                              style={"color": COLORS["text_3"]}),
                    html.Span("INFEASIBLE", className="rc-score-badge",
                              style={"color": COLORS["text_3"], "borderColor": COLORS["border"]}),
                ]),
                html.Div(opt.infeasibility_reason, className="rc-desc",
                         style={"color": COLORS["text_3"]}),
            ])
        else:
            # Score bar width
            bar_pct = max(4, int(opt.score))

            card = html.Div(
                className="recovery-card",
                style={"borderTopColor": sc["accent"]},
                children=[
                    # Header
                    html.Div(className="rc-header", children=[
                        html.Span(sc["icon"], className="rc-icon",
                                  style={"color": sc["accent"]}),
                        html.Span(opt.label, className="rc-title",
                                  style={"color": sc["accent"]}),
                        html.Span(s_label, className="rc-score-badge",
                                  style={"color": s_color, "borderColor": s_color}),
                    ]),

                    # Score bar
                    html.Div(className="rc-score-bar-bg", children=[
                        html.Div(className="rc-score-bar-fill",
                                 style={"width": f"{bar_pct}%",
                                        "background": sc["accent"]}),
                    ]),

                    # Description
                    html.Div(opt.description, className="rc-desc"),

                    # Metrics grid
                    html.Div(className="rc-metrics", children=[
                        html.Div(className="rc-metric", children=[
                            html.Div("DELAY CUT",  className="rc-metric-key"),
                            html.Div(f"{opt.delay_reduction_min:.0f}m",
                                     className="rc-metric-val",
                                     style={"color": sc["accent"]}),
                            html.Div(f"({opt.delay_reduction_pct:.0f}%)",
                                     className="rc-metric-sub"),
                        ]),
                        html.Div(className="rc-metric", children=[
                            html.Div("DIRECT COST", className="rc-metric-key"),
                            html.Div(f"${opt.direct_cost_usd:,.0f}",
                                     className="rc-metric-val",
                                     style={"color": COLORS["text_2"]}),
                            html.Div("activation", className="rc-metric-sub"),
                        ]),
                        html.Div(className="rc-metric", children=[
                            html.Div("NET COST",   className="rc-metric-key"),
                            html.Div(f"${opt.net_cost_usd:,.0f}",
                                     className="rc-metric-val",
                                     style={"color": COLORS["text_1"]}),
                            html.Div("vs baseline", className="rc-metric-sub"),
                        ]),
                        html.Div(className="rc-metric", children=[
                            html.Div("PAX SAVED",  className="rc-metric-key"),
                            html.Div(str(opt.pax_saved),
                                     className="rc-metric-val",
                                     style={"color": COLORS["teal"]}),
                            html.Div(f"{opt.pax_stranded} stranded", className="rc-metric-sub"),
                        ]),
                    ]),

                    # Expandable action log
                    html.Details(className="rc-log-details", children=[
                        html.Summary("▸ ACTION LOG", className="rc-log-toggle"),
                        html.Div(className="rc-log-body", children=[
                            html.Div(line, className="rc-log-line") for line in opt.action_log
                        ]),
                    ]),

                    # Apply button
                    html.Button(
                        f"APPLY {opt.strategy}",
                        id={"type": "recovery-select-btn", "index": idx},
                        className="rc-apply-btn",
                        style={"borderColor": sc["accent"], "color": sc["accent"]},
                        n_clicks=0,
                    ),
                ]
            )
        cards.append(card)

    return [html.Div(className="recovery-cards-grid", children=cards)]


def _build_gantt(df: pd.DataFrame, result, recovery_label: str = None) -> go.Figure:
    """Horizontal Gantt — one bar per flight, colored by status."""
    rows = []
    for _, r in df.iterrows():
        if r["direction"] == "inbound":
            if pd.isna(r.get("arr_scheduled")) or pd.isna(r.get("arr_actual")):
                continue
            start = r["arr_scheduled"]
            end   = r["arr_actual"]
        else:
            if pd.isna(r.get("dep_scheduled")) or pd.isna(r.get("dep_actual")):
                continue
            start = r["dep_scheduled"]
            end   = r["dep_actual"]

        if (end - start).total_seconds() < 300:
            end = start + pd.Timedelta(minutes=5)

        rows.append({
            "flight":    r["flight_id"],
            "start":     start,
            "end":       end,
            "status":    r.get("status", "scheduled"),
            "aircraft":  r.get("aircraft_reg", ""),
            "direction": r["direction"],
        })

    if not rows:
        from ui.layout import empty_gantt_fig
        return empty_gantt_fig()

    status_colors = {
        "scheduled":    COLORS["normal"],
        "landed":       "#2A5A4A",
        "trigger":      COLORS["cyan"],
        "delayed":      COLORS["delayed"],
        "delayed_high": COLORS["orange"],
        "critical":     COLORS["red"],
        "recovered":    "#1A7A4A",
        "cancelled":    "#4A1A2A",
    }

    fig = go.Figure()
    for row in sorted(rows, key=lambda x: x["start"]):
        color = status_colors.get(row["status"], COLORS["normal"])
        opacity = 0.4 if row["status"] == "cancelled" else 0.85
        fig.add_trace(go.Bar(
            x=[(row["end"] - row["start"]).total_seconds() / 60],
            y=[row["flight"]],
            base=[row["start"]],
            orientation="h",
            marker=dict(color=color, opacity=opacity, line=dict(width=0)),
            hovertemplate=(
                f"<b>{row['flight']}</b><br>"
                f"{row['direction'].upper()} · {row['aircraft']}<br>"
                f"Start: {row['start'].strftime('%H:%M')}<br>"
                f"End:   {row['end'].strftime('%H:%M')}<br>"
                f"Status: {row['status'].upper()}"
                "<extra></extra>"
            ),
            showlegend=False,
            name=row["flight"],
        ))

    title_text = f"AFTER RECOVERY: {recovery_label}" if recovery_label else ""

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor ="rgba(0,0,0,0)",
        margin=dict(l=90, r=10, t=4 if not recovery_label else 24, b=30),
        barmode="overlay",
        title=dict(text=title_text, font=dict(
            family="Barlow Condensed", size=12,
            color="#00D4A0"), x=0.01) if recovery_label else {},
        font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=10),
        xaxis=dict(
            type="date",
            showgrid=True, gridcolor="rgba(28,45,72,0.6)",
            zeroline=False,
            tickfont=dict(size=9, color=COLORS["text_3"]),
            tickformat="%H:%M",
        ),
        yaxis=dict(
            showgrid=False, zeroline=False,
            tickfont=dict(size=9, color=COLORS["text_3"]),
            autorange="reversed",
        ),
        hoverlabel=dict(
            bgcolor=COLORS["bg_2"],
            bordercolor=COLORS["border"],
            font=dict(family="JetBrains Mono", size=11, color=COLORS["text_1"]),
        ),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Monte Carlo + PDF Export Callbacks
# ══════════════════════════════════════════════════════════════════════════════

def register_phase3_callbacks(app, G, df):
    """Phase 3 callbacks — Monte Carlo runner and PDF export."""
    from engine.monte_carlo import run_monte_carlo, build_heatmap_data
    from engine.recovery import evaluate_all_recovery_options
    from engine.cascade import run_cascade
    from engine.pdf_report import generate_pdf_report
    import plotly.graph_objects as go
    import json, os, base64, tempfile
    from dash import Input, Output, State, html, dcc
    from dash.exceptions import PreventUpdate

    # ── Monte Carlo runner ─────────────────────────────────────────────────────
    @app.callback(
        Output("mc-status-bar",    "children"),
        Output("mc-charts",        "children"),
        Output("mc-network-stats", "children"),
        Output("mc-result-store",  "data"),
        Input("mc-run-btn", "n_clicks"),
        prevent_initial_call=True
    )
    def run_mc(n_clicks):
        if not n_clicks:
            raise PreventUpdate

        mc = run_monte_carlo(G, df, n_scenarios=500)
        ns = mc.network_summary

        # ── Status bar ──────────────────────────────────────────────────────
        status = html.Div(className="mc-status-done", children=[
            html.Span(f"✓  {ns.n_scenarios} scenarios · {ns.runtime_seconds:.2f}s",
                      style={"color": COLORS["teal"],
                             "fontFamily": "JetBrains Mono", "fontSize": "11px"}),
            html.Span(f"  |  {ns.zero_cascade_pct:.1f}% no cascade  "
                      f"|  {ns.critical_scenario_pct:.1f}% critical",
                      style={"color": COLORS["text_3"],
                             "fontFamily": "JetBrains Mono", "fontSize": "11px"}),
        ])

        # ── Cascade cost distribution histogram ──────────────────────────────
        cost_fig = go.Figure()
        cost_fig.add_trace(go.Histogram(
            x=mc.cost_samples,
            nbinsx=50,
            marker=dict(color=COLORS["gold"], opacity=0.75,
                        line=dict(width=0)),
            name="Cascade Cost",
        ))
        cost_fig.add_vline(
            x=ns.p90_cost_usd, line_dash="dash",
            line_color=COLORS["orange"], line_width=1.5,
            annotation_text=f"P90 ${ns.p90_cost_usd:,.0f}",
            annotation_font=dict(color=COLORS["orange"],
                                 family="JetBrains Mono", size=9),
        )
        cost_fig.add_vline(
            x=ns.p99_cost_usd, line_dash="dash",
            line_color=COLORS["red"], line_width=1.5,
            annotation_text=f"P99 ${ns.p99_cost_usd:,.0f}",
            annotation_font=dict(color=COLORS["red"],
                                 family="JetBrains Mono", size=9),
        )
        cost_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=50, r=20, t=28, b=40),
            title=dict(text="CASCADE COST DISTRIBUTION",
                       font=dict(family="Barlow Condensed", size=11,
                                 color=COLORS["text_3"]), x=0),
            font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=9),
            xaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)",
                       zeroline=False,
                       title=dict(text="Cost (USD)", font=dict(size=9))),
            yaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)",
                       zeroline=False,
                       title=dict(text="Scenarios", font=dict(size=9))),
            showlegend=False,
        )

        # ── Delay distribution histogram ─────────────────────────────────────
        delay_fig = go.Figure()
        delay_fig.add_trace(go.Histogram(
            x=mc.delay_samples,
            nbinsx=40,
            marker=dict(color=COLORS["cyan"], opacity=0.70,
                        line=dict(width=0)),
            name="Initial Delay",
        ))
        delay_fig.add_vline(
            x=17.5, line_dash="dot",
            line_color=COLORS["teal"], line_width=1.5,
            annotation_text="EUROCONTROL avg 17.5m",
            annotation_font=dict(color=COLORS["teal"],
                                 family="JetBrains Mono", size=9),
        )
        delay_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=50, r=20, t=28, b=40),
            title=dict(text="SAMPLED DELAY DISTRIBUTION (LOGNORMAL)",
                       font=dict(family="Barlow Condensed", size=11,
                                 color=COLORS["text_3"]), x=0),
            font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=9),
            xaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)",
                       zeroline=False, range=[0, 200],
                       title=dict(text="Initial Delay (min)", font=dict(size=9))),
            yaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)",
                       zeroline=False,
                       title=dict(text="Scenarios", font=dict(size=9))),
            showlegend=False,
        )

        # ── Risk heatmap ─────────────────────────────────────────────────────
        hm = build_heatmap_data(mc, G)

        heatmap_fig = go.Figure(data=go.Heatmap(
            z=hm["z"],
            x=hm["x"],
            y=hm["y"],
            text=hm["annots"],
            texttemplate="%{text}",
            colorscale=[
                [0.0, COLORS["bg_2"]],
                [0.3, "#1A4A6A"],
                [0.6, COLORS["gold"]],
                [0.85, COLORS["orange"]],
                [1.0, COLORS["red"]],
            ],
            showscale=True,
            colorbar=dict(
                thickness=10,
                tickfont=dict(family="JetBrains Mono", size=8,
                              color=COLORS["text_3"]),
                tickcolor=COLORS["text_3"],
            ),
            hoverongaps=False,
            hovertemplate=(
                "<b>%{x}</b><br>%{y}: %{text}<extra></extra>"
            ),
        ))
        heatmap_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=130, r=20, t=28, b=60),
            title=dict(text="PER-FLIGHT RISK HEATMAP",
                       font=dict(family="Barlow Condensed", size=11,
                                 color=COLORS["text_3"]), x=0),
            font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=9),
            xaxis=dict(tickfont=dict(size=9), tickangle=-40),
            yaxis=dict(tickfont=dict(size=9)),
            hoverlabel=dict(
                bgcolor=COLORS["bg_2"],
                bordercolor=COLORS["border"],
                font=dict(family="JetBrains Mono", size=11,
                          color=COLORS["text_1"]),
            ),
        )

        charts = [
            html.Div(className="mc-chart-cell", children=[
                dcc.Graph(figure=cost_fig, config={"displayModeBar": False},
                          style={"height": "220px"}),
            ]),
            html.Div(className="mc-chart-cell", children=[
                dcc.Graph(figure=delay_fig, config={"displayModeBar": False},
                          style={"height": "220px"}),
            ]),
            html.Div(className="mc-chart-cell mc-chart-wide", children=[
                dcc.Graph(figure=heatmap_fig, config={"displayModeBar": False},
                          style={"height": "220px"}),
            ]),
        ]

        # ── Network summary stats ─────────────────────────────────────────────
        top_trig = ns.top_triggers[:3]
        stats = html.Div(className="mc-stats-row", children=[
            html.Div(className="metric-box gold", children=[
                html.Div("MEAN CASCADE / SCENARIO", className="metric-key"),
                html.Div(f"{ns.mean_flights_affected:.1f} flights", className="metric-val"),
            ]),
            html.Div(className="metric-box red", children=[
                html.Div("P90 COST", className="metric-key"),
                html.Div(f"${ns.p90_cost_usd:,.0f}", className="metric-val",
                         style={"fontSize": "16px"}),
            ]),
            html.Div(className="metric-box cyan", children=[
                html.Div("CRITICAL SCENARIOS", className="metric-key"),
                html.Div(f"{ns.critical_scenario_pct:.1f}%", className="metric-val"),
            ]),
            html.Div(className="metric-box teal", children=[
                html.Div("TOP TRIGGER", className="metric-key"),
                html.Div(top_trig[0][0] if top_trig else "—", className="metric-val"),
            ]),
        ])

        # Serialise mc summary for PDF export
        mc_store = json.dumps({
            "n_scenarios":           ns.n_scenarios,
            "mean_flights_affected": ns.mean_flights_affected,
            "p50_flights_affected":  ns.p50_flights_affected,
            "p90_flights_affected":  ns.p90_flights_affected,
            "p99_flights_affected":  ns.p99_flights_affected,
            "mean_cost_usd":         ns.mean_cost_usd,
            "p50_cost_usd":          ns.p50_cost_usd,
            "p90_cost_usd":          ns.p90_cost_usd,
            "p99_cost_usd":          ns.p99_cost_usd,
            "mean_total_delay":      ns.mean_total_delay,
            "p90_total_delay":       ns.p90_total_delay,
            "zero_cascade_pct":      ns.zero_cascade_pct,
            "critical_scenario_pct": ns.critical_scenario_pct,
            "top_triggers":          ns.top_triggers,
            # risk profiles (serialisable subset)
            "risk_profiles": {
                fid: {
                    "risk_label": p.risk_label,
                    "risk_score": p.risk_score,
                    "victim_probability": p.victim_probability,
                    "trigger_avg_cost": p.trigger_avg_cost,
                    "direction": p.direction,
                    "origin": p.origin,
                    "destination": p.destination,
                    "aircraft_type": p.aircraft_type,
                }
                for fid, p in mc.risk_profiles.items()
            },
        })

        return status, charts, stats, mc_store

    # ── PDF export ─────────────────────────────────────────────────────────────
    @app.callback(
        Output("pdf-download", "data"),
        Input("pdf-export-btn",   "n_clicks"),
        State("cascade-result-store", "data"),
        State("flight-select",   "value"),
        State("delay-slider",    "value"),
        State("mc-result-store", "data"),
        prevent_initial_call=True
    )
    def export_pdf(n_clicks, cascade_store, flight_id, delay_min, mc_store):
        if not n_clicks:
            raise PreventUpdate

        # Re-run cascade for current selection
        if not flight_id or not delay_min:
            raise PreventUpdate

        result  = run_cascade(G, flight_id, float(delay_min))
        options = evaluate_all_recovery_options(G, df, result)

        cascade_dict = result.summary()
        cascade_dict["events"] = [
            {"flight_id": e.flight_id, "direction": "outbound",
             "edge_type": e.edge_type, "delay_min": e.delay_min,
             "pax_affected": e.pax_affected, "cost_usd": e.cost_usd,
             "severity": e.severity}
            for e in result.events
        ]

        opt_dicts = [
            {"label": o.label, "feasible": o.feasible,
             "delay_reduction_min": o.delay_reduction_min,
             "delay_reduction_pct": o.delay_reduction_pct,
             "direct_cost_usd": o.direct_cost_usd,
             "net_cost_usd": o.net_cost_usd,
             "pax_saved": o.pax_saved, "score": o.score}
            for o in options
        ]

        # Re-run MC if no stored result (lightweight)
        from engine.monte_carlo import run_monte_carlo, MonteCarloResult
        mc = run_monte_carlo(G, df, n_scenarios=500)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            path = tmp.name

        generate_pdf_report(cascade_dict, opt_dicts, mc, path)

        with open(path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(path)

        filename = f"SILSILA_{flight_id}_{int(delay_min)}min_{result.flights_affected}affected.pdf"
        return dcc.send_bytes(pdf_bytes, filename=filename)
