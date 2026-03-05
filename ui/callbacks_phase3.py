"""
callbacks_phase3.py
-------------------
Monte Carlo analysis and PDF export callbacks.
"""

from __future__ import annotations

import json
import os
import tempfile

from dash import Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from engine.cascade import run_cascade
from engine.config import MC_SCENARIOS
from engine.monte_carlo import build_heatmap_data, run_monte_carlo
from engine.pdf_report import generate_pdf_report
from engine.recovery import evaluate_all_recovery_options
from ui.callbacks_core import COLORS
from ui.session_state import (
    deserialize_cascade_store,
    deserialize_mc_store,
    deserialize_recovery_store,
    serialize_cascade_result,
    serialize_recovery_options,
)


def register_phase3_callbacks(app, G, df):
    """Register Monte Carlo and export callbacks."""

    @app.callback(
        Output("mc-status-bar", "children"),
        Output("mc-charts", "children"),
        Output("mc-network-stats", "children"),
        Output("mc-result-store", "data"),
        Input("mc-run-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def run_mc(n_clicks):
        if not n_clicks:
            raise PreventUpdate

        mc = run_monte_carlo(G, df, n_scenarios=MC_SCENARIOS)
        ns = mc.network_summary

        status = html.Div(className="mc-status-done", children=[
            html.Span(
                f"✓  {ns.n_scenarios} scenarios · {ns.runtime_seconds:.2f}s",
                style={"color": COLORS["teal"], "fontFamily": "JetBrains Mono", "fontSize": "11px"},
            ),
            html.Span(
                f"  |  {ns.zero_cascade_pct:.1f}% no cascade  |  {ns.critical_scenario_pct:.1f}% critical",
                style={"color": COLORS["text_3"], "fontFamily": "JetBrains Mono", "fontSize": "11px"},
            ),
        ])

        cost_fig = go.Figure()
        cost_fig.add_trace(go.Histogram(
            x=mc.cost_samples,
            nbinsx=50,
            marker=dict(color=COLORS["gold"], opacity=0.75, line=dict(width=0)),
            name="Cascade Cost",
        ))
        cost_fig.add_vline(
            x=ns.p90_cost_usd,
            line_dash="dash",
            line_color=COLORS["orange"],
            line_width=1.5,
            annotation_text=f"P90 ${ns.p90_cost_usd:,.0f}",
            annotation_font=dict(color=COLORS["orange"], family="JetBrains Mono", size=9),
        )
        cost_fig.add_vline(
            x=ns.p99_cost_usd,
            line_dash="dash",
            line_color=COLORS["red"],
            line_width=1.5,
            annotation_text=f"P99 ${ns.p99_cost_usd:,.0f}",
            annotation_font=dict(color=COLORS["red"], family="JetBrains Mono", size=9),
        )
        cost_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=50, r=20, t=28, b=40),
            title=dict(text="CASCADE COST DISTRIBUTION",
                       font=dict(family="Barlow Condensed", size=11, color=COLORS["text_3"]), x=0),
            font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=9),
            xaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False,
                       title=dict(text="Cost (USD)", font=dict(size=9))),
            yaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False,
                       title=dict(text="Scenarios", font=dict(size=9))),
            showlegend=False,
        )

        delay_fig = go.Figure()
        delay_fig.add_trace(go.Histogram(
            x=mc.delay_samples,
            nbinsx=40,
            marker=dict(color=COLORS["cyan"], opacity=0.70, line=dict(width=0)),
            name="Initial Delay",
        ))
        delay_fig.add_vline(
            x=17.5,
            line_dash="dot",
            line_color=COLORS["teal"],
            line_width=1.5,
            annotation_text="EUROCONTROL avg 17.5m",
            annotation_font=dict(color=COLORS["teal"], family="JetBrains Mono", size=9),
        )
        delay_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=50, r=20, t=28, b=40),
            title=dict(text="SAMPLED DELAY DISTRIBUTION (LOGNORMAL)",
                       font=dict(family="Barlow Condensed", size=11, color=COLORS["text_3"]), x=0),
            font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=9),
            xaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False, range=[0, 200],
                       title=dict(text="Initial Delay (min)", font=dict(size=9))),
            yaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False,
                       title=dict(text="Scenarios", font=dict(size=9))),
            showlegend=False,
        )

        heatmap = build_heatmap_data(mc, G)
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=heatmap["z"],
            x=heatmap["x"],
            y=heatmap["y"],
            text=heatmap["annots"],
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
                tickfont=dict(family="JetBrains Mono", size=8, color=COLORS["text_3"]),
                tickcolor=COLORS["text_3"],
            ),
            hoverongaps=False,
            hovertemplate="<b>%{x}</b><br>%{y}: %{text}<extra></extra>",
        ))
        heatmap_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=130, r=20, t=28, b=60),
            title=dict(text="PER-FLIGHT RISK HEATMAP",
                       font=dict(family="Barlow Condensed", size=11, color=COLORS["text_3"]), x=0),
            font=dict(family="JetBrains Mono", color=COLORS["text_2"], size=9),
            xaxis=dict(tickfont=dict(size=9), tickangle=-40),
            yaxis=dict(tickfont=dict(size=9)),
            hoverlabel=dict(
                bgcolor=COLORS["bg_2"],
                bordercolor=COLORS["border"],
                font=dict(family="JetBrains Mono", size=11, color=COLORS["text_1"]),
            ),
        )

        charts = [
            html.Div(className="mc-chart-cell", children=[
                dcc.Graph(figure=cost_fig, config={"displayModeBar": False}, style={"height": "220px"}),
            ]),
            html.Div(className="mc-chart-cell", children=[
                dcc.Graph(figure=delay_fig, config={"displayModeBar": False}, style={"height": "220px"}),
            ]),
            html.Div(className="mc-chart-cell mc-chart-wide", children=[
                dcc.Graph(figure=heatmap_fig, config={"displayModeBar": False}, style={"height": "220px"}),
            ]),
        ]

        top_triggers = ns.top_triggers[:3]
        stats = html.Div(className="mc-stats-row", children=[
            html.Div(className="metric-box gold", children=[
                html.Div("MEAN CASCADE / SCENARIO", className="metric-key"),
                html.Div(f"{ns.mean_flights_affected:.1f} flights", className="metric-val"),
            ]),
            html.Div(className="metric-box red", children=[
                html.Div("P90 COST", className="metric-key"),
                html.Div(f"${ns.p90_cost_usd:,.0f}", className="metric-val", style={"fontSize": "16px"}),
            ]),
            html.Div(className="metric-box cyan", children=[
                html.Div("CRITICAL SCENARIOS", className="metric-key"),
                html.Div(f"{ns.critical_scenario_pct:.1f}%", className="metric-val"),
            ]),
            html.Div(className="metric-box teal", children=[
                html.Div("TOP TRIGGER", className="metric-key"),
                html.Div(top_triggers[0][0] if top_triggers else "—", className="metric-val"),
            ]),
        ])

        mc_store = json.dumps({
            "n_scenarios": ns.n_scenarios,
            "mean_flights_affected": ns.mean_flights_affected,
            "p50_flights_affected": ns.p50_flights_affected,
            "p90_flights_affected": ns.p90_flights_affected,
            "p99_flights_affected": ns.p99_flights_affected,
            "mean_cost_usd": ns.mean_cost_usd,
            "p50_cost_usd": ns.p50_cost_usd,
            "p90_cost_usd": ns.p90_cost_usd,
            "p99_cost_usd": ns.p99_cost_usd,
            "mean_total_delay": ns.mean_total_delay,
            "p90_total_delay": ns.p90_total_delay,
            "zero_cascade_pct": ns.zero_cascade_pct,
            "critical_scenario_pct": ns.critical_scenario_pct,
            "top_triggers": ns.top_triggers,
            "risk_profiles": {
                fid: {
                    "risk_label": profile.risk_label,
                    "risk_score": profile.risk_score,
                    "victim_probability": profile.victim_probability,
                    "trigger_avg_cost": profile.trigger_avg_cost,
                    "direction": profile.direction,
                    "origin": profile.origin,
                    "destination": profile.destination,
                    "aircraft_type": profile.aircraft_type,
                }
                for fid, profile in mc.risk_profiles.items()
            },
        })

        return status, charts, stats, mc_store

    @app.callback(
        Output("pdf-download", "data"),
        Input("pdf-export-btn", "n_clicks"),
        State("cascade-result-store", "data"),
        State("flight-select", "value"),
        State("delay-slider", "value"),
        State("mc-result-store", "data"),
        State("recovery-options-store", "data"),
        State("selected-recovery-store", "data"),
        prevent_initial_call=True,
    )
    def export_pdf(n_clicks, cascade_store, flight_id, delay_min, mc_store, recovery_store, selected_recovery_store):
        if not n_clicks:
            raise PreventUpdate
        if not flight_id or not delay_min:
            raise PreventUpdate

        selected_strategy = None
        if selected_recovery_store:
            try:
                selected_strategy = json.loads(selected_recovery_store).get("strategy")
            except (TypeError, json.JSONDecodeError, AttributeError):
                selected_strategy = None

        cascade_dict = deserialize_cascade_store(cascade_store)
        if cascade_dict is None:
            result = run_cascade(G, flight_id, float(delay_min))
            cascade_dict = json.loads(serialize_cascade_result(result, G))

        options = deserialize_recovery_store(recovery_store)
        if not options:
            result = run_cascade(G, flight_id, float(delay_min))
            options = deserialize_recovery_store(
                serialize_recovery_options(evaluate_all_recovery_options(G, df, result))
            )
        option_payload = [dict(option) for option in options]
        if selected_strategy:
            for option in option_payload:
                if option["strategy"] == selected_strategy:
                    option["label"] = f"{option['label']} [SELECTED]"
                    break

        mc = deserialize_mc_store(mc_store)
        if mc is None:
            mc = run_monte_carlo(G, df, n_scenarios=MC_SCENARIOS)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            path = tmp.name

        generate_pdf_report(cascade_dict, option_payload, mc, path)
        with open(path, "rb") as handle:
            pdf_bytes = handle.read()
        os.unlink(path)

        filename = f"SILSILA_{flight_id}_{int(delay_min)}min_{cascade_dict.get('flights_affected', 0)}affected.pdf"
        return dcc.send_bytes(pdf_bytes, filename=filename)
