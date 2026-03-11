"""
analysis_views.py
-----------------
View builders for Monte Carlo and sensitivity analysis panels.
"""

from __future__ import annotations

from dash import dcc, html
import plotly.graph_objects as go

from engine.monte_carlo import build_heatmap_data
from ui.session_state import serialize_mc_result


def build_monte_carlo_outputs(mc, graph, colors: dict[str, str]):
    """Build the Phase 3 Monte Carlo UI outputs from a computed result."""
    ns = mc.network_summary

    status = html.Div(
        className="mc-status-done",
        children=[
            html.Span(
                f"{ns.n_scenarios} scenarios · {ns.runtime_seconds:.2f}s",
                style={"color": colors["teal"], "fontFamily": "JetBrains Mono", "fontSize": "11px"},
            ),
            html.Span(
                f"  |  {ns.zero_cascade_pct:.1f}% no cascade  |  {ns.critical_scenario_pct:.1f}% critical",
                style={"color": colors["text_3"], "fontFamily": "JetBrains Mono", "fontSize": "11px"},
            ),
        ],
    )

    cost_fig = _build_cost_distribution_figure(mc, colors)
    delay_fig = _build_delay_distribution_figure(mc, colors)
    heatmap_fig = _build_heatmap_figure(mc, graph, colors)

    charts = [
        html.Div(
            className="mc-chart-cell",
            children=[dcc.Graph(figure=cost_fig, config={"displayModeBar": False}, style={"height": "220px"})],
        ),
        html.Div(
            className="mc-chart-cell",
            children=[dcc.Graph(figure=delay_fig, config={"displayModeBar": False}, style={"height": "220px"})],
        ),
        html.Div(
            className="mc-chart-cell mc-chart-wide",
            children=[dcc.Graph(figure=heatmap_fig, config={"displayModeBar": False}, style={"height": "220px"})],
        ),
    ]

    top_triggers = ns.top_triggers[:3]
    stats = html.Div(
        className="mc-stats-row",
        children=[
            html.Div(
                className="metric-box gold",
                children=[
                    html.Div("MEAN CASCADE / SCENARIO", className="metric-key"),
                    html.Div(f"{ns.mean_flights_affected:.1f} flights", className="metric-val"),
                ],
            ),
            html.Div(
                className="metric-box red",
                children=[
                    html.Div("P90 COST", className="metric-key"),
                    html.Div(f"${ns.p90_cost_usd:,.0f}", className="metric-val", style={"fontSize": "16px"}),
                ],
            ),
            html.Div(
                className="metric-box cyan",
                children=[
                    html.Div("CRITICAL SCENARIOS", className="metric-key"),
                    html.Div(f"{ns.critical_scenario_pct:.1f}%", className="metric-val"),
                ],
            ),
            html.Div(
                className="metric-box teal",
                children=[
                    html.Div("TOP TRIGGER", className="metric-key"),
                    html.Div(top_triggers[0][0] if top_triggers else "-", className="metric-val"),
                ],
            ),
        ],
    )

    return status, charts, stats, serialize_mc_result(mc)


def build_sensitivity_outputs(points, flight_id: str, delay_min: float, colors: dict[str, str]):
    """Build the sensitivity-panel UI outputs from computed scenario points."""
    x_vals = [point.min_turnaround_min for point in points]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x_vals,
            y=[point.mean_flights_affected for point in points],
            mode="lines+markers",
            name="Flights affected",
            line=dict(color=colors["cyan"], width=2),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x_vals,
            y=[point.mean_total_delay_min for point in points],
            mode="lines+markers",
            name="Total delay (min)",
            yaxis="y2",
            line=dict(color=colors["gold"], width=2),
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=50, r=50, t=25, b=40),
        title=dict(
            text=f"TURNAROUND SENSITIVITY · {flight_id} @ +{int(delay_min)}m",
            font=dict(family="Barlow Condensed", size=11, color=colors["text_3"]),
            x=0,
        ),
        font=dict(family="JetBrains Mono", color=colors["text_2"], size=9),
        xaxis=dict(
            title=dict(text="Minimum Turnaround (min)", font=dict(size=9)),
            tickmode="array",
            tickvals=x_vals,
            showgrid=True,
            gridcolor="rgba(28,45,72,0.5)",
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(text="Flights Affected", font=dict(size=9)),
            showgrid=True,
            gridcolor="rgba(28,45,72,0.5)",
            zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Total Delay (min)", font=dict(size=9)),
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
        ),
        legend=dict(orientation="h", x=0, y=1.15),
    )

    baseline = next((point for point in points if point.min_turnaround_min == 45.0), points[0])
    tightest = min(points, key=lambda point: point.min_turnaround_min)
    loosest = max(points, key=lambda point: point.min_turnaround_min)

    status = html.Div(
        className="mc-status-done",
        children=[
            html.Span(
                f"Compared {len(points)} turnaround assumptions for {flight_id}",
                style={"color": colors["teal"], "fontFamily": "JetBrains Mono", "fontSize": "11px"},
            ),
            html.Span(
                f"  |  baseline 45m -> {baseline.mean_flights_affected:.1f} flights hit",
                style={"color": colors["text_3"], "fontFamily": "JetBrains Mono", "fontSize": "11px"},
            ),
        ],
    )
    summary = html.Div(
        className="mc-stats-row",
        children=[
            html.Div(
                className="metric-box cyan",
                children=[
                    html.Div("35 MIN TURN", className="metric-key"),
                    html.Div(f"{tightest.mean_flights_affected:.1f} flights", className="metric-val"),
                ],
            ),
            html.Div(
                className="metric-box gold",
                children=[
                    html.Div("45 MIN BASELINE", className="metric-key"),
                    html.Div(f"{baseline.mean_total_delay_min:.0f}m", className="metric-val"),
                ],
            ),
            html.Div(
                className="metric-box red",
                children=[
                    html.Div("65 MIN TURN", className="metric-key"),
                    html.Div(f"{loosest.mean_flights_affected:.1f} flights", className="metric-val"),
                ],
            ),
            html.Div(
                className="metric-box teal",
                children=[
                    html.Div("DELTA VS 45", className="metric-key"),
                    html.Div(
                        f"{loosest.mean_total_delay_min - baseline.mean_total_delay_min:+.0f}m",
                        className="metric-val",
                    ),
                ],
            ),
        ],
    )

    return status, figure, summary


def _build_cost_distribution_figure(mc, colors: dict[str, str]) -> go.Figure:
    ns = mc.network_summary
    figure = go.Figure()
    figure.add_trace(
        go.Histogram(
            x=mc.cost_samples,
            nbinsx=50,
            marker=dict(color=colors["gold"], opacity=0.75, line=dict(width=0)),
            name="Cascade Cost",
        )
    )
    figure.add_vline(
        x=ns.p90_cost_usd,
        line_dash="dash",
        line_color=colors["orange"],
        line_width=1.5,
        annotation_text=f"P90 ${ns.p90_cost_usd:,.0f}",
        annotation_font=dict(color=colors["orange"], family="JetBrains Mono", size=9),
    )
    figure.add_vline(
        x=ns.p99_cost_usd,
        line_dash="dash",
        line_color=colors["red"],
        line_width=1.5,
        annotation_text=f"P99 ${ns.p99_cost_usd:,.0f}",
        annotation_font=dict(color=colors["red"], family="JetBrains Mono", size=9),
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=50, r=20, t=28, b=40),
        title=dict(text="CASCADE COST DISTRIBUTION", font=dict(family="Barlow Condensed", size=11, color=colors["text_3"]), x=0),
        font=dict(family="JetBrains Mono", color=colors["text_2"], size=9),
        xaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False, title=dict(text="Cost (USD)", font=dict(size=9))),
        yaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False, title=dict(text="Scenarios", font=dict(size=9))),
        showlegend=False,
    )
    return figure


def _build_delay_distribution_figure(mc, colors: dict[str, str]) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Histogram(
            x=mc.delay_samples,
            nbinsx=40,
            marker=dict(color=colors["cyan"], opacity=0.70, line=dict(width=0)),
            name="Initial Delay",
        )
    )
    figure.add_vline(
        x=17.5,
        line_dash="dot",
        line_color=colors["teal"],
        line_width=1.5,
        annotation_text="EUROCONTROL avg 17.5m",
        annotation_font=dict(color=colors["teal"], family="JetBrains Mono", size=9),
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=50, r=20, t=28, b=40),
        title=dict(text="SAMPLED DELAY DISTRIBUTION (LOGNORMAL)", font=dict(family="Barlow Condensed", size=11, color=colors["text_3"]), x=0),
        font=dict(family="JetBrains Mono", color=colors["text_2"], size=9),
        xaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False, range=[0, 200], title=dict(text="Initial Delay (min)", font=dict(size=9))),
        yaxis=dict(showgrid=True, gridcolor="rgba(28,45,72,0.5)", zeroline=False, title=dict(text="Scenarios", font=dict(size=9))),
        showlegend=False,
    )
    return figure


def _build_heatmap_figure(mc, graph, colors: dict[str, str]) -> go.Figure:
    heatmap = build_heatmap_data(mc, graph)
    figure = go.Figure(
        data=go.Heatmap(
            z=heatmap["z"],
            x=heatmap["x"],
            y=heatmap["y"],
            text=heatmap["annots"],
            texttemplate="%{text}",
            colorscale=[
                [0.0, colors["bg_2"]],
                [0.3, "#1A4A6A"],
                [0.6, colors["gold"]],
                [0.85, colors["orange"]],
                [1.0, colors["red"]],
            ],
            showscale=True,
            colorbar=dict(
                thickness=10,
                tickfont=dict(family="JetBrains Mono", size=8, color=colors["text_3"]),
                tickcolor=colors["text_3"],
            ),
            hoverongaps=False,
            hovertemplate="<b>%{x}</b><br>%{y}: %{text}<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=130, r=20, t=28, b=60),
        title=dict(text="PER-FLIGHT RISK HEATMAP", font=dict(family="Barlow Condensed", size=11, color=colors["text_3"]), x=0),
        font=dict(family="JetBrains Mono", color=colors["text_2"], size=9),
        xaxis=dict(tickfont=dict(size=9), tickangle=-40),
        yaxis=dict(tickfont=dict(size=9)),
        hoverlabel=dict(
            bgcolor=colors["bg_2"],
            bordercolor=colors["border"],
            font=dict(family="JetBrains Mono", size=11, color=colors["text_1"]),
        ),
    )
    return figure
