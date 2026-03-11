"""
callbacks_core.py
-----------------
Core Dash callbacks for live simulation, recovery, and shared figure builders.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dash import Input, Output, State, html
import plotly.graph_objects as go
import pandas as pd

from engine.cyto_graph import build_cyto_elements, build_cyto_stylesheet
from dash.exceptions import PreventUpdate

from ui.session_state import (
    cascade_store_matches_request,
    serialize_cascade_result,
    serialize_recovery_options,
)
from ui.workflows import run_simulation_bundle, select_recovery_option

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
    "normal":   "#2A4A7A",
    "trigger":  "#00C8FF",
    "delayed":  "#E8A020",
    "delayed_h":"#FF6B35",
    "critical": "#FF3D5A",
    "landed":   "#2A5A4A",
}


def register_callbacks(app, G, df):
    """Register live simulation and recovery callbacks."""
    cyto_stylesheet = build_cyto_stylesheet()
    base_elements = build_cyto_elements(G, df)
    COLORS["recovered"] = "#1A7A4A"
    COLORS["cancelled"] = "#4A1A2A"

    @app.callback(
        Output("live-clock", "children"),
        Input("clock-interval", "n_intervals"),
    )
    def update_clock(_):
        now = datetime.now(tz=timezone.utc)
        ast_hour = (now.hour + 3) % 24
        return f"{ast_hour:02d}:{now.minute:02d}:{now.second:02d}"

    @app.callback(
        Output("delay-display", "children"),
        Input("delay-slider", "value"),
    )
    def update_delay_display(val):
        if val is None:
            return "— min"
        if val >= 60:
            hours, minutes = divmod(val, 60)
            return [f"{hours}h {minutes:02d}", html.Span(" min")]
        return [str(val), html.Span(" min")]

    @app.callback(
        Output("selected-flight-card", "children"),
        Input("flight-select", "value"),
    )
    def update_flight_card(flight_id):
        if not flight_id or flight_id not in G.nodes:
            return html.Div()
        data = G.nodes[flight_id]
        direction = data.get("direction", "")
        origin = data.get("origin", "—")
        dest = data.get("destination", "—")
        ref_time = data.get("arr_actual" if direction == "inbound" else "dep_scheduled")
        time_str = ref_time.strftime("%H:%M") if pd.notna(ref_time) else "—"

        return html.Div(className="flight-card", children=[
            html.Div([
                html.Span(flight_id, className="flight-card-route"),
                html.Span(" · ", style={"color": COLORS["text_3"]}),
                html.Span(
                    "INBOUND" if direction == "inbound" else "OUTBOUND",
                    className="tag tag-inbound" if direction == "inbound" else "tag tag-outbound",
                    style={"marginLeft": "4px", "verticalAlign": "middle"},
                ),
            ]),
            html.Div(
                f"{origin} → {dest}",
                style={"fontFamily": "JetBrains Mono", "fontSize": "12px",
                       "color": COLORS["text_2"], "marginTop": "4px"},
            ),
            html.Div(className="flight-card-meta", children=[
                html.Div(className="meta-item", children=[
                    html.Div("AIRCRAFT", className="meta-key"),
                    html.Div(data.get("aircraft_reg", "—"), className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("TYPE", className="meta-key"),
                    html.Div(data.get("aircraft_type", "—"), className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("PAX ONBOARD", className="meta-key"),
                    html.Div(f"{data.get('pax', 0):,}", className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("SCHED TIME", className="meta-key"),
                    html.Div(time_str, className="meta-val"),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("SLACK", className="meta-key"),
                    html.Div(
                        f"{data.get('turnaround_slack_min', 0):.0f} min",
                        className="meta-val",
                        style={"color": COLORS["gold"] if data.get("turnaround_slack_min", 999) < 30 else COLORS["text_2"]},
                    ),
                ]),
                html.Div(className="meta-item", children=[
                    html.Div("CREW", className="meta-key"),
                    html.Div(data.get("crew_id", "—"), className="meta-val"),
                ]),
            ]),
        ])

    @app.callback(
        Output("cascade-result-store", "data"),
        Output("network-graph", "elements", allow_duplicate=True),
        Output("network-graph", "stylesheet", allow_duplicate=True),
        Output("cascade-log", "children"),
        Output("affected-count", "children"),
        Output("gantt-chart", "figure"),
        Output("summary-metrics", "children"),
        Output("recovery-cards", "children"),
        Output("recovery-status-badge", "children"),
        Output("optimizer-summary", "children"),
        Output("recovery-options-store", "data"),
        Output("selected-recovery-store", "data"),
        Input("trigger-btn", "n_clicks"),
        Input("reset-btn", "n_clicks"),
        State("flight-select", "value"),
        State("delay-slider", "value"),
        prevent_initial_call=True,
    )
    def run_simulation(trigger_clicks, reset_clicks, flight_id, delay_min):
        from dash import ctx

        triggered = ctx.triggered_id
        empty_recovery = _empty_recovery_cards()

        if triggered == "reset-btn":
            return (
                None,
                base_elements,
                cyto_stylesheet,
                _empty_log(),
                "0 AFFECTED",
                _build_gantt(df, None),
                html.Div(),
                empty_recovery,
                "AWAITING CASCADE",
                html.Div(),
                None,
                None,
            )

        if not flight_id or not delay_min:
            return (
                None,
                base_elements,
                cyto_stylesheet,
                _empty_log(),
                "0 AFFECTED",
                _build_gantt(df, None),
                html.Div(),
                empty_recovery,
                "AWAITING CASCADE",
                html.Div(),
                None,
                None,
            )

        bundle = run_simulation_bundle(G, df, flight_id, float(delay_min))

        return (
            serialize_cascade_result(bundle.cascade_result, G),
            build_cyto_elements(G, bundle.cascaded_df, flight_id, bundle.affected_ids),
            cyto_stylesheet,
            _build_cascade_log(bundle.cascade_result),
            f"{bundle.cascade_result.flights_affected} AFFECTED",
            _build_gantt(bundle.cascaded_df, bundle.cascade_result),
            _build_summary_metrics(bundle.cascade_result),
            _build_recovery_cards(bundle.recovery_options),
            f"{len([option for option in bundle.recovery_options if option.feasible])} OPTIONS READY",
            _build_optimizer_summary(bundle.optimization),
            serialize_recovery_options(bundle.recovery_options),
            None,
        )

    @app.callback(
        Output("cascade-result-store", "data", allow_duplicate=True),
        Output("network-graph", "elements", allow_duplicate=True),
        Output("network-graph", "stylesheet", allow_duplicate=True),
        Output("cascade-log", "children", allow_duplicate=True),
        Output("affected-count", "children", allow_duplicate=True),
        Output("gantt-chart", "figure", allow_duplicate=True),
        Output("summary-metrics", "children", allow_duplicate=True),
        Output("recovery-cards", "children", allow_duplicate=True),
        Output("recovery-status-badge", "children", allow_duplicate=True),
        Output("optimizer-summary", "children", allow_duplicate=True),
        Output("recovery-options-store", "data", allow_duplicate=True),
        Output("selected-recovery-store", "data", allow_duplicate=True),
        Input("flight-select", "value"),
        Input("delay-slider", "value"),
        State("cascade-result-store", "data"),
        prevent_initial_call=True,
    )
    def invalidate_stale_scenario(flight_id, delay_min, cascade_store):
        if not cascade_store:
            raise PreventUpdate
        if cascade_store_matches_request(cascade_store, flight_id, delay_min):
            raise PreventUpdate
        return (
            None,
            base_elements,
            cyto_stylesheet,
            _empty_log(),
            "0 AFFECTED",
            _build_gantt(df, None),
            html.Div(),
            _empty_recovery_cards(),
            "AWAITING CASCADE",
            html.Div(),
            None,
            None,
        )

    @app.callback(
        Output("gantt-chart", "figure", allow_duplicate=True),
        Output("network-graph", "elements", allow_duplicate=True),
        Output("selected-recovery-store", "data"),
        Input({"type": "recovery-select-btn", "index": 0}, "n_clicks"),
        Input({"type": "recovery-select-btn", "index": 1}, "n_clicks"),
        Input({"type": "recovery-select-btn", "index": 2}, "n_clicks"),
        State("flight-select", "value"),
        State("delay-slider", "value"),
        State("recovery-options-store", "data"),
        State("cascade-result-store", "data"),
        prevent_initial_call=True,
    )
    def apply_recovery(c0, c1, c2, flight_id, delay_min, recovery_store, cascade_store):
        from dash import ctx

        if not ctx.triggered_id or not flight_id or not recovery_store:
            raise PreventUpdate
        if not cascade_store_matches_request(cascade_store, flight_id, delay_min):
            raise PreventUpdate

        triggered_idx = ctx.triggered_id.get("index", 0)
        selection = select_recovery_option(recovery_store, triggered_idx)
        if selection is None:
            raise PreventUpdate

        return (
            _build_gantt(selection.recovered_df, None, recovery_label=selection.option_payload.get("label")),
            build_cyto_elements(G, selection.recovered_df, flight_id, selection.affected_ids),
            selection.selected_store,
        )

    @app.callback(
        Output("cyto-node-info", "children"),
        Input("network-graph", "tapNodeData"),
        prevent_initial_call=True,
    )
    def show_node_info(node_data):
        if not node_data:
            return ""
        fid = node_data.get("id", "")
        orig = node_data.get("origin", "")
        dest = node_data.get("destination", "")
        pax = node_data.get("pax", 0)
        slack = node_data.get("slack", 0)
        return f"{fid}  {orig}→{dest}  PAX {pax:,}  slack {slack:.0f}m"


def _build_cascade_log(result) -> list:
    if not result.events:
        return [html.Div(className="log-empty", children=[
            html.Div("◎", className="icon"),
            html.Div("NO CASCADE"),
            html.Div("Delay absorbed within existing slack",
                     style={"opacity": "0.5", "textTransform": "none"}),
        ])]

    items = []
    for event in result.events:
        items.append(html.Div(
            className=f"cascade-item severity-{event.severity}",
            children=[
                html.Div(className="cascade-item-top", children=[
                    html.Span([
                        event.flight_id,
                        html.Span(" / ".join(getattr(event, "impact_channels", [event.edge_type])), className=f"ci-type-tag {event.edge_type}"),
                    ], className="ci-flight"),
                    html.Span(f"+{event.delay_min:.0f} min", className=f"ci-delay {event.severity}"),
                ]),
                html.Div([
                    html.Span(f"via {event.caused_by}", style={"marginRight": "8px"}),
                    html.Span(f"PAX: {event.pax_affected:,}"),
                    html.Span(f"  ${event.cost_usd:,.0f}", style={"color": COLORS["text_3"]}),
                ], className="ci-meta"),
                html.Div(
                    " → ".join(event.propagation_path),
                    style={"fontFamily": "JetBrains Mono", "fontSize": "9px",
                           "color": COLORS["text_3"], "marginTop": "3px",
                           "whiteSpace": "nowrap", "overflow": "hidden",
                           "textOverflow": "ellipsis"},
                ),
            ],
        ))
    return items


def _build_summary_metrics(result) -> html.Div:
    summary = result.summary()
    return html.Div([
        html.Div(className="metrics-row", children=[
            html.Div(className="metric-box gold", children=[
                html.Div("FLIGHTS HIT", className="metric-key"),
                html.Div(summary["flights_affected"], className="metric-val"),
            ]),
            html.Div(className="metric-box red", children=[
                html.Div("TOTAL DELAY", className="metric-key"),
                html.Div(f"{summary['total_delay_min']:.0f}m", className="metric-val"),
            ]),
        ]),
        html.Div(className="metrics-row", children=[
            html.Div(className="metric-box cyan", children=[
                html.Div("PAX AFFECTED", className="metric-key"),
                html.Div(f"{summary['total_pax_affected']:,}", className="metric-val"),
            ]),
            html.Div(className="metric-box teal", children=[
                html.Div("EST. COST", className="metric-key"),
                html.Div(f"${summary['estimated_cost_usd']:,.0f}", className="metric-val",
                         style={"fontSize": "16px"}),
            ]),
        ]),
    ])


def _build_optimizer_summary(optimization) -> html.Div:
    if not optimization.candidates:
        return html.Div()
    frontier = ", ".join(optimization.frontier_labels) if optimization.frontier_labels else "—"
    best = optimization.candidates[0]
    return html.Div(className="mc-stats-row", children=[
        html.Div(className="metric-box teal", children=[
            html.Div("OPTIMIZER PICK", className="metric-key"),
            html.Div(optimization.best_label or "—", className="metric-val"),
        ]),
        html.Div(className="metric-box cyan", children=[
            html.Div("OBJECTIVE SCORE", className="metric-key"),
            html.Div(f"{best.objective_score:.3f}", className="metric-val"),
        ]),
        html.Div(className="metric-box gold", children=[
            html.Div("PARETO FRONT", className="metric-key"),
            html.Div(frontier, className="metric-val", style={"fontSize": "12px"}),
        ]),
    ])


def _empty_log() -> list:
    return [html.Div(className="log-empty", children=[
        html.Div("◌", className="icon"),
        html.Div("AWAITING INPUT"),
        html.Div("Select a flight and set delay",
                 style={"opacity": "0.5", "textTransform": "none", "letterSpacing": "0"}),
    ])]


def _empty_recovery_cards() -> list:
    return [html.Div(className="log-empty", children=[
        html.Div("◈", className="icon"),
        html.Div("RUN SIMULATION FIRST"),
        html.Div("Recovery options appear after cascade analysis",
                 style={"opacity": "0.5", "textTransform": "none", "letterSpacing": "0"}),
    ])]


def _build_recovery_cards(options: list) -> list:
    if not options:
        return _empty_recovery_cards()

    strategy_colors = {
        "SWAP": {"accent": "#00C8FF", "icon": "⇄"},
        "DELAY": {"accent": "#E8A020", "icon": "⏱"},
        "CANCEL": {"accent": "#FF3D5A", "icon": "✕"},
    }
    score_labels = {
        (80, 100): ("RECOMMENDED", "#00D4A0"),
        (50, 80): ("VIABLE", "#E8A020"),
        (0, 50): ("COSTLY", "#FF6B35"),
    }

    def score_badge(score):
        for (lo, hi), badge in score_labels.items():
            if lo <= score <= hi:
                return badge
        return "REVIEW", "#8CA0C0"

    cards = []
    for idx, option in enumerate(options):
        strategy = strategy_colors.get(option.strategy, {"accent": "#8CA0C0", "icon": "?"})
        label, label_color = score_badge(option.score)

        if not option.feasible:
            card = html.Div(className="recovery-card recovery-card-infeasible", children=[
                html.Div(className="rc-header", children=[
                    html.Span(strategy["icon"], className="rc-icon", style={"color": COLORS["text_3"]}),
                    html.Span(option.label, className="rc-title", style={"color": COLORS["text_3"]}),
                    html.Span("INFEASIBLE", className="rc-score-badge",
                              style={"color": COLORS["text_3"], "borderColor": COLORS["border"]}),
                ]),
                html.Div(option.infeasibility_reason, className="rc-desc", style={"color": COLORS["text_3"]}),
            ])
        else:
            card = html.Div(className="recovery-card", style={"borderTopColor": strategy["accent"]}, children=[
                html.Div(className="rc-header", children=[
                    html.Span(strategy["icon"], className="rc-icon", style={"color": strategy["accent"]}),
                    html.Span(option.label, className="rc-title", style={"color": strategy["accent"]}),
                    html.Span(label, className="rc-score-badge",
                              style={"color": label_color, "borderColor": label_color}),
                ]),
                html.Div(
                    option.recommendation or ("PARETO-EFFICIENT" if option.pareto_efficient else "DOMINATED TRADEOFF"),
                    className="rc-desc",
                    style={
                        "color": COLORS["teal"] if option.pareto_efficient else COLORS["text_3"],
                        "marginTop": "6px",
                        "fontSize": "11px",
                    },
                ),
                html.Div(className="rc-score-bar-bg", children=[
                    html.Div(className="rc-score-bar-fill",
                             style={"width": f"{max(4, int(option.score))}%", "background": strategy["accent"]}),
                ]),
                html.Div(option.description, className="rc-desc"),
                html.Div(className="rc-metrics", children=[
                    html.Div(className="rc-metric", children=[
                        html.Div("DELAY CUT", className="rc-metric-key"),
                        html.Div(f"{option.delay_reduction_min:.0f}m", className="rc-metric-val",
                                 style={"color": strategy["accent"]}),
                        html.Div(f"({option.delay_reduction_pct:.0f}%)", className="rc-metric-sub"),
                    ]),
                    html.Div(className="rc-metric", children=[
                        html.Div("DIRECT COST", className="rc-metric-key"),
                        html.Div(f"${option.direct_cost_usd:,.0f}", className="rc-metric-val",
                                 style={"color": COLORS["text_2"]}),
                        html.Div("activation", className="rc-metric-sub"),
                    ]),
                    html.Div(className="rc-metric", children=[
                        html.Div("NET COST", className="rc-metric-key"),
                        html.Div(f"${option.net_cost_usd:,.0f}", className="rc-metric-val",
                                 style={"color": COLORS["text_1"]}),
                        html.Div("vs baseline", className="rc-metric-sub"),
                    ]),
                    html.Div(className="rc-metric", children=[
                        html.Div("PAX SAVED", className="rc-metric-key"),
                        html.Div(str(option.pax_saved), className="rc-metric-val",
                                 style={"color": COLORS["teal"]}),
                        html.Div(f"{option.pax_stranded} stranded", className="rc-metric-sub"),
                    ]),
                ]),
                html.Details(className="rc-log-details", children=[
                    html.Summary("▸ ACTION LOG", className="rc-log-toggle"),
                    html.Div(className="rc-log-body", children=[
                        html.Div(line, className="rc-log-line") for line in option.action_log
                    ]),
                ]),
                html.Button(
                    f"APPLY {option.strategy}",
                    id={"type": "recovery-select-btn", "index": idx},
                    className="rc-apply-btn",
                    style={"borderColor": strategy["accent"], "color": strategy["accent"]},
                    n_clicks=0,
                ),
            ])
        cards.append(card)

    return [html.Div(className="recovery-cards-grid", children=cards)]


def _build_gantt(df: pd.DataFrame, result, recovery_label: str | None = None) -> go.Figure:
    rows = []
    for _, row in df.iterrows():
        if row["direction"] == "inbound":
            if pd.isna(row.get("arr_scheduled")) or pd.isna(row.get("arr_actual")):
                continue
            start = row["arr_scheduled"]
            end = row["arr_actual"]
        else:
            if pd.isna(row.get("dep_scheduled")) or pd.isna(row.get("dep_actual")):
                continue
            start = row["dep_scheduled"]
            end = row["dep_actual"]

        if (end - start).total_seconds() < 300:
            end = start + pd.Timedelta(minutes=5)

        rows.append({
            "flight": row["flight_id"],
            "start": start,
            "end": end,
            "status": row.get("status", "scheduled"),
            "aircraft": row.get("aircraft_reg", ""),
            "direction": row["direction"],
        })

    if not rows:
        from ui.layout import empty_gantt_fig
        return empty_gantt_fig()

    status_colors = {
        "scheduled": COLORS["normal"],
        "landed": "#2A5A4A",
        "trigger": COLORS["cyan"],
        "delayed": COLORS["delayed"],
        "delayed_high": COLORS["orange"],
        "critical": COLORS["red"],
        "recovered": "#1A7A4A",
        "cancelled": "#4A1A2A",
    }

    fig = go.Figure()
    for row in sorted(rows, key=lambda item: item["start"]):
        fig.add_trace(go.Bar(
            x=[(row["end"] - row["start"]).total_seconds() / 60],
            y=[row["flight"]],
            base=[row["start"]],
            orientation="h",
            marker=dict(
                color=status_colors.get(row["status"], COLORS["normal"]),
                opacity=0.4 if row["status"] == "cancelled" else 0.85,
                line=dict(width=0),
            ),
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
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=90, r=10, t=4 if not recovery_label else 24, b=30),
        barmode="overlay",
        title=dict(text=title_text, font=dict(
            family="Barlow Condensed", size=12, color="#00D4A0"), x=0.01) if recovery_label else {},
        font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=10),
        xaxis=dict(
            type="date",
            showgrid=True,
            gridcolor="rgba(28,45,72,0.6)",
            zeroline=False,
            tickfont=dict(size=9, color=COLORS["text_3"]),
            tickformat="%H:%M",
        ),
        yaxis=dict(
            showgrid=False,
            zeroline=False,
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








