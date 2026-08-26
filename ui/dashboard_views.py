from __future__ import annotations

import json

from dash import html
import pandas as pd
import plotly.graph_objects as go


def workflow_state_badge_class(state: str | None) -> str:
    return f"workflow-state-badge status-pill {status_slug(state)}"


def recovery_status_badge_text(state: str | None, has_selection: bool, has_options: bool) -> str:
    normalized = (state or "AWAITING CASCADE").upper()
    if normalized == "AWAITING CASCADE":
        return "AWAITING CASCADE"
    if normalized == "SIMULATED":
        return "OPTIONS READY" if has_options else "NO VIABLE PLAN"
    if normalized == "RECOMMENDED":
        return "PLAN SELECTED" if has_selection else "OPTIONS READY"
    if normalized == "REVIEWED":
        return "REVIEWED"
    if normalized == "ACCEPTED":
        return "PLAN ACCEPTED"
    if normalized == "OVERRIDDEN":
        return "OVERRIDDEN"
    return normalized


def recovery_status_badge_class(state: str | None, has_selection: bool, has_options: bool) -> str:
    normalized = (state or "AWAITING CASCADE").upper()
    if normalized in {"REVIEWED", "ACCEPTED", "OVERRIDDEN"}:
        return f"panel-badge status-pill {status_slug(normalized)}"
    if normalized == "RECOMMENDED" and has_selection:
        return f"panel-badge status-pill {status_slug(normalized)}"
    if has_selection:
        return f"panel-badge status-pill {status_slug(state or 'RECOMMENDED')}"
    if has_options:
        return "panel-badge status-pill status-ready"
    return "panel-badge status-pill status-awaiting"


def workflow_button_states(state: str | None, has_selection: bool) -> tuple[bool, bool, bool]:
    normalized = (state or "AWAITING CASCADE").upper()
    if normalized == "AWAITING CASCADE":
        return True, True, True
    if normalized == "SIMULATED":
        return not has_selection, True, False
    if normalized == "RECOMMENDED":
        return False, True, False
    if normalized == "REVIEWED":
        return True, False, False
    return True, True, True


def parse_selected_strategy(selected_recovery_store: str | None) -> str | None:
    if not selected_recovery_store:
        return None
    try:
        payload = json.loads(selected_recovery_store)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    strategy = payload.get("strategy")
    return str(strategy) if strategy else None


def build_cascade_log(result, colors: dict) -> list:
    if not result.events:
        return [html.Div(className="log-empty", children=[
            html.Div("◎", className="icon"),
            html.Div("NO DOWNSTREAM IMPACT"),
            html.Div("Current delay is absorbed within available slack.", style={"opacity": "0.5", "textTransform": "none"}),
        ])]

    items = []
    for event in result.events:
        items.append(html.Div(
            className=f"cascade-item severity-{event.severity}",
            children=[
                html.Div(className="cascade-item-top", children=[
                    html.Span([
                        event.flight_id,
                        html.Span(
                            " / ".join(getattr(event, "impact_channels", [event.edge_type])),
                            className=f"ci-type-tag {event.edge_type}",
                        ),
                    ], className="ci-flight"),
                    html.Span(f"+{event.delay_min:.0f} min", className=f"ci-delay {event.severity}"),
                ]),
                html.Div([
                    html.Span(f"via {event.caused_by}", style={"marginRight": "8px"}),
                    html.Span(f"PAX: {event.pax_affected:,}"),
                    html.Span(f"  ${event.cost_usd:,.0f}", style={"color": colors["text_3"]}),
                ], className="ci-meta"),
                html.Div(
                    " -> ".join(event.propagation_path),
                    style={
                        "fontFamily": "JetBrains Mono",
                        "fontSize": "9px",
                        "color": colors["text_3"],
                        "marginTop": "3px",
                        "whiteSpace": "nowrap",
                        "overflow": "hidden",
                        "textOverflow": "ellipsis",
                    },
                ),
            ],
        ))
    return items


def build_summary_metrics(result, colors: dict, confidence=None, data_quality=None) -> html.Div:
    summary = result.summary()
    signals = [
        _signal_chip("TRIGGER", f"{summary['trigger']} +{int(summary['trigger_delay_min'])}m", "cyan"),
        _signal_chip("DEPTH", f"{summary['cascade_depth']} hops", "gold"),
    ]

    if summary["critical_count"]:
        signals.append(_signal_chip("CRITICAL", str(summary["critical_count"]), "red"))
    if summary["high_count"]:
        signals.append(_signal_chip("HIGH", str(summary["high_count"]), "orange"))
    if summary["medium_count"]:
        signals.append(_signal_chip("MEDIUM", str(summary["medium_count"]), "gold"))

    if data_quality is not None:
        signals.append(_signal_chip("DATA", f"{getattr(data_quality, 'mode', 'LOCAL')} / {getattr(data_quality, 'status', 'UNKNOWN')}", "teal"))
    if confidence is not None:
        signals.append(_signal_chip("CONFIDENCE", f"{int(confidence.score * 100)}% {confidence.label}", "cyan"))

    rationale = None
    if confidence is not None and confidence.reasons:
        rationale = " • ".join(confidence.reasons[:2])

    return html.Div(className="impact-overview", children=[
        html.Div(className="impact-overview-head", children=[
            html.Div(className="impact-headline-block", children=[
                html.Div("CURRENT IMPACT", className="impact-kicker"),
                html.Div(_impact_headline(summary), className="impact-headline"),
                html.Div(_impact_subhead(summary), className="impact-subhead"),
            ]),
            html.Div(className="impact-severity-board", children=[
                _mini_stat("Flights", summary["flights_affected"], "gold"),
                _mini_stat("Delay", f"{summary['total_delay_min']:.0f}m", "red"),
                _mini_stat("PAX", f"{summary['total_pax_affected']:,}", "cyan"),
                _mini_stat("Cost", f"${summary['estimated_cost_usd']:,.0f}", "teal"),
            ]),
        ]),
        html.Div(className="impact-signal-row", children=signals),
        html.Div(className="impact-summary-blurb", children=_impact_brief(summary)),
        html.Div(rationale, className="impact-rationale") if rationale else html.Div(),
    ])


def build_optimizer_summary(optimization, colors: dict) -> html.Div:
    if not optimization.candidates:
        return html.Div()
    best = optimization.candidates[0]
    return html.Div(className="optimizer-strip", children=[
        html.Div(className="optimizer-callout", children=[
            html.Div("TOP RECOVERY PLAN", className="metric-key"),
            html.Div(optimization.best_label or "—", className="optimizer-title"),
            html.Div("Highest-ranked feasible recovery under the current scoring model.", className="optimizer-note"),
        ]),
        html.Div(className="optimizer-metrics", children=[
            _mini_stat("Objective", f"{best.objective_score:.3f}", "cyan"),
            _mini_stat("Frontier", f"{len(optimization.frontier_labels)} plans", "gold"),
            _mini_stat("Scenario", "Saved", "teal"),
        ]),
    ])


def empty_log() -> list:
    return [html.Div(className="log-empty", children=[
        html.Div("◌", className="icon"),
        html.Div("AWAITING INPUT"),
        html.Div(
            "Trigger and delay are loaded. Run SIMULATE CASCADE to create a scenario.",
            style={"opacity": "0.5", "textTransform": "none", "letterSpacing": "0"},
        ),
    ])]


def empty_recovery_cards(message: str = "Run a simulation to generate recovery plans.") -> list:
    return [html.Div(className="log-empty", children=[
        html.Div("◈", className="icon"),
        html.Div("RUN SIMULATION FIRST"),
        html.Div(message, style={"opacity": "0.5", "textTransform": "none", "letterSpacing": "0"}),
    ])]


def empty_comparison_strip(message: str = "Select a recovery option to compare delay relief, passenger protection, and cost exposure.") -> list:
    return [html.Div(className="comparison-empty", children=message)]


def build_comparison_strip(option_payload: dict, colors: dict) -> list:
    label = option_payload.get("label", "—")
    return [html.Div(className="comparison-strip-grid", children=[
        html.Div(className="comparison-card comparison-card-featured", children=[
            html.Div("SELECTED PLAN", className="metric-key"),
            html.Div(label, className="comparison-featured-title"),
            html.Div(option_payload.get("strategy", "UNKNOWN"), className="comparison-featured-tag"),
        ]),
        html.Div(className="comparison-card", children=[
            html.Div("DELAY CUT", className="metric-key"),
            html.Div(f"{option_payload.get('delay_reduction_min', 0):.0f}m", className="metric-val", style={"fontSize": "16px", "color": colors["gold"]}),
        ]),
        html.Div(className="comparison-card", children=[
            html.Div("PAX SAVED", className="metric-key"),
            html.Div(str(option_payload.get("pax_saved", 0)), className="metric-val", style={"fontSize": "16px", "color": colors["teal"]}),
        ]),
        html.Div(className="comparison-card", children=[
            html.Div("NET COST", className="metric-key"),
            html.Div(f"${option_payload.get('net_cost_usd', 0):,.0f}", className="metric-val", style={"fontSize": "16px", "color": colors["text_1"]}),
        ]),
    ])]


def build_recovery_cards(options: list, colors: dict, selected_strategy: str | None = None) -> list:
    if not options:
        return empty_recovery_cards()

    strategy_colors = {
        "SWAP": {"accent": "#D0A7D9", "icon": "<->"},
        "DELAY": {"accent": "#E6C78E", "icon": "T"},
        "CANCEL": {"accent": "#FF7A86", "icon": "X"},
    }
    score_labels = {
        (80, 100): ("TOP PLAN", "#75E0C0"),
        (50, 80): ("VIABLE", "#E6C78E"),
        (0, 50): ("HIGH COST", "#F3A074"),
    }

    def score_badge(score):
        for (lo, hi), badge in score_labels.items():
            if lo <= score <= hi:
                return badge
        return "REVIEW", "#82768A"

    cards = []
    for idx, option in enumerate(options):
        strategy_name = _option_value(option, "strategy", "UNKNOWN")
        option_label = _option_value(option, "label", "—")
        strategy = strategy_colors.get(strategy_name, {"accent": "#82768A", "icon": "?"})
        score_value = float(_option_value(option, "score", 0) or 0)
        label, label_color = score_badge(score_value)
        feasible = bool(_option_value(option, "feasible", False))
        is_selected = bool(selected_strategy and strategy_name == selected_strategy)

        if not feasible:
            card = html.Div(className="recovery-card recovery-card-infeasible", children=[
                html.Div(className="rc-header", children=[
                    html.Span(strategy["icon"], className="rc-icon", style={"color": colors["text_3"]}),
                    html.Span(option_label, className="rc-title", style={"color": colors["text_3"]}),
                    html.Span("INFEASIBLE", className="rc-score-badge", style={"color": colors["text_3"], "borderColor": colors["border"]}),
                ]),
                html.Div(_option_value(option, "infeasibility_reason", "Unavailable"), className="rc-desc", style={"color": colors["text_3"]}),
            ])
        else:
            card_classes = "recovery-card recovery-card-active" if is_selected else "recovery-card"
            button_classes = "rc-apply-btn rc-apply-btn-active" if is_selected else "rc-apply-btn"
            button_label = "CURRENT PLAN" if is_selected else "SELECT PLAN"
            recommendation = _option_value(option, "recommendation")
            pareto = bool(_option_value(option, "pareto_efficient", False))
            card = html.Div(className=card_classes, style={"borderTopColor": strategy["accent"]}, children=[
                html.Div("SELECTED PLAN" if is_selected else "RECOVERY OPTION", className="rc-active-banner"),
                html.Div(className="rc-header", children=[
                    html.Span(strategy["icon"], className="rc-icon", style={"color": strategy["accent"]}),
                    html.Span(option_label, className="rc-title", style={"color": strategy["accent"]}),
                    html.Span(label, className="rc-score-badge", style={"color": label_color, "borderColor": label_color}),
                ]),
                html.Div(
                    _display_recommendation(recommendation, pareto),
                    className="rc-desc",
                    style={"color": colors["teal"] if pareto else colors["text_3"], "marginTop": "6px", "fontSize": "11px"},
                ),
                html.Div(className="rc-score-bar-bg", children=[
                    html.Div(className="rc-score-bar-fill", style={"width": f"{max(4, int(score_value))}%", "background": strategy["accent"]})
                ]),
                html.Div(_option_value(option, "description", "No description available."), className="rc-desc"),
                html.Div(className="rc-metrics", children=[
                    html.Div(className="rc-metric", children=[
                        html.Div("DELAY CUT", className="rc-metric-key"),
                        html.Div(f"{_option_value(option, 'delay_reduction_min', 0):.0f}m", className="rc-metric-val", style={"color": strategy["accent"]}),
                        html.Div(f"({_option_value(option, 'delay_reduction_pct', 0):.0f}%)", className="rc-metric-sub"),
                    ]),
                    html.Div(className="rc-metric", children=[
                        html.Div("DIRECT COST", className="rc-metric-key"),
                        html.Div(f"${_option_value(option, 'direct_cost_usd', 0):,.0f}", className="rc-metric-val", style={"color": colors["text_2"]}),
                        html.Div("activation", className="rc-metric-sub"),
                    ]),
                    html.Div(className="rc-metric", children=[
                        html.Div("NET COST", className="rc-metric-key"),
                        html.Div(f"${_option_value(option, 'net_cost_usd', 0):,.0f}", className="rc-metric-val", style={"color": colors["text_1"]}),
                        html.Div("vs baseline", className="rc-metric-sub"),
                    ]),
                    html.Div(className="rc-metric", children=[
                        html.Div("PAX SAVED", className="rc-metric-key"),
                        html.Div(str(_option_value(option, "pax_saved", 0)), className="rc-metric-val", style={"color": colors["teal"]}),
                        html.Div(f"{_option_value(option, 'pax_stranded', 0)} stranded", className="rc-metric-sub"),
                    ]),
                ]),
                html.Details(className="rc-log-details", children=[
                    html.Summary("▸ ACTION LOG", className="rc-log-toggle"),
                    html.Div(
                        className="rc-log-body",
                        children=[html.Div(line, className="rc-log-line") for line in list(_option_value(option, "action_log", []))],
                    ),
                ]),
                html.Button(
                    button_label,
                    id={"type": "recovery-select-btn", "index": idx},
                    className=button_classes,
                    style={"borderColor": strategy["accent"], "color": strategy["accent"]},
                    n_clicks=0,
                    disabled=is_selected,
                ),
            ])
        cards.append(card)

    return [html.Div(className="recovery-cards-grid", children=cards)]


def build_gantt(df: pd.DataFrame, result, colors: dict, recovery_label: str | None = None) -> go.Figure:
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
        "scheduled": colors["normal"],
        "landed": "#2A5A4A",
        "trigger": colors["cyan"],
        "delayed": colors["delayed"],
        "delayed_high": colors["orange"],
        "critical": colors["red"],
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
                color=status_colors.get(row["status"], colors["normal"]),
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
        title=dict(text=title_text, font=dict(family="Barlow Condensed", size=12, color="#75E0C0"), x=0.01) if recovery_label else {},
        font=dict(family="JetBrains Mono", color=colors["text_2"], size=10),
        xaxis=dict(type="date", showgrid=True, gridcolor="rgba(28,45,72,0.6)", zeroline=False, tickfont=dict(size=9, color=colors["text_3"]), tickformat="%H:%M"),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=9, color=colors["text_3"]), autorange="reversed"),
        hoverlabel=dict(bgcolor=colors["bg_2"], bordercolor=colors["border"], font=dict(family="JetBrains Mono", size=11, color=colors["text_1"])),
    )
    return fig


def build_recovery_cards_from_store(recovery_store: str | None, colors: dict, selected_recovery_store: str | None) -> list:
    if not recovery_store:
        return empty_recovery_cards()
    try:
        payload = json.loads(recovery_store)
    except (TypeError, json.JSONDecodeError):
        return empty_recovery_cards("Recovery payload is unavailable.")
    if not isinstance(payload, list):
        return empty_recovery_cards("Recovery payload is unavailable.")
    return build_recovery_cards(payload, colors, selected_strategy=parse_selected_strategy(selected_recovery_store))


def status_slug(status: str | None) -> str:
    normalized = (status or "AWAITING CASCADE").strip().upper().replace("_", " ")
    normalized = {
        "AWAITING CASCADE": "awaiting",
        "OPTIONS READY": "ready",
    }.get(normalized, normalized.lower().replace(" ", "-"))
    return f"status-{normalized}"


def _option_value(option, key: str, default=None):
    if isinstance(option, dict):
        return option.get(key, default)
    return getattr(option, key, default)


def _impact_headline(summary: dict) -> str:
    flights = summary["flights_affected"]
    if flights == 0:
        return "No downstream impact detected."
    if summary["critical_count"]:
        return "Critical impact. Recovery action required."
    if summary["cascade_depth"] >= 3:
        return "Network disruption is spreading."
    return "Contained impact. Recovery plans ready."


def _impact_subhead(summary: dict) -> str:
    flights = int(summary["flights_affected"])
    return f"{summary['trigger']} +{int(summary['trigger_delay_min'])} min now affects {_count_phrase(flights, 'downstream flight')}."


def _impact_brief(summary: dict) -> str:
    if summary["flights_affected"] == 0:
        return "Current delay is being absorbed within available slack. A recovery action is optional."
    if summary["critical_count"]:
        return "At least one downstream leg is in the critical band. Review and approve a recovery plan before execution."
    if summary["total_pax_stranded"]:
        return f"{_count_phrase(summary['total_pax_stranded'], 'passenger')} currently exposed to a missed connection. Prioritize passenger protection in plan selection."
    return "Current impact is limited. Review the recovery plans before approval."


def _signal_chip(label: str, value: str, tone: str) -> html.Div:
    return html.Div(className=f"impact-signal impact-signal-{tone}", children=[
        html.Div(label, className="impact-signal-label"),
        html.Div(value, className="impact-signal-value"),
    ])


def _mini_stat(label: str, value, tone: str) -> html.Div:
    return html.Div(className=f"mini-stat mini-stat-{tone}", children=[
        html.Div(label.upper(), className="mini-stat-label"),
        html.Div(str(value), className="mini-stat-value"),
    ])


def _count_phrase(count: int | float, singular: str, plural: str | None = None) -> str:
    value = int(count)
    noun = singular if value == 1 else (plural or f"{singular}s")
    return f"{value} {noun}"


def _display_recommendation(recommendation: str | None, pareto_efficient: bool) -> str:
    normalized = (recommendation or "").strip().upper()
    replacements = {
        "PARETO": "FRONTIER OPTION",
        "PARETO-EFFICIENT": "FRONTIER OPTION",
        "PARETO · TOP SCORE": "FRONTIER · TOP SCORE",
        "DOMINATED": "LOWER-RANKED OPTION",
        "DOMINATED TRADEOFF": "LOWER-RANKED OPTION",
    }
    if normalized in replacements:
        return replacements[normalized]
    if recommendation:
        return recommendation
    return "FRONTIER OPTION" if pareto_efficient else "LOWER-RANKED OPTION"
