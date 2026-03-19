"""
callbacks_core.py
-----------------
Core Dash callbacks for live simulation, recovery, and shared figure builders.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

from dash import ALL, Input, Output, State, html
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
import pandas as pd

from engine.cyto_graph import build_cyto_elements, build_cyto_stylesheet
from ui.dashboard_views import (
    build_cascade_log,
    build_comparison_strip,
    build_gantt,
    build_optimizer_summary,
    build_recovery_cards,
    build_recovery_cards_from_store,
    build_summary_metrics,
    empty_comparison_strip,
    empty_log,
    empty_recovery_cards,
    parse_selected_strategy,
    recovery_status_badge_text,
    recovery_status_badge_class,
    workflow_button_states,
    workflow_state_badge_class,
)
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



def register_callbacks(app, G, df, platform=None):
    """Register live simulation and recovery callbacks."""
    cyto_stylesheet = build_cyto_stylesheet()
    empty_graph_elements = []
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
                style={"fontFamily": "JetBrains Mono", "fontSize": "12px", "color": COLORS["text_2"], "marginTop": "4px"},
            ),
            html.Div(className="flight-card-meta", children=[
                html.Div(className="meta-item", children=[html.Div("AIRCRAFT", className="meta-key"), html.Div(data.get("aircraft_reg", "—"), className="meta-val")]),
                html.Div(className="meta-item", children=[html.Div("TYPE", className="meta-key"), html.Div(data.get("aircraft_type", "—"), className="meta-val")]),
                html.Div(className="meta-item", children=[html.Div("PAX ONBOARD", className="meta-key"), html.Div(f"{data.get('pax', 0):,}", className="meta-val")]),
                html.Div(className="meta-item", children=[html.Div("SCHED TIME", className="meta-key"), html.Div(time_str, className="meta-val")]),
                html.Div(className="meta-item", children=[
                    html.Div("SLACK", className="meta-key"),
                    html.Div(
                        f"{data.get('turnaround_slack_min', 0):.0f} min",
                        className="meta-val",
                        style={"color": COLORS["gold"] if data.get("turnaround_slack_min", 999) < 30 else COLORS["text_2"]},
                    ),
                ]),
                html.Div(className="meta-item", children=[html.Div("CREW", className="meta-key"), html.Div(data.get("crew_id", "—"), className="meta-val")]),
            ]),
        ])

    @app.callback(
        Output("cascade-result-store", "data"),
        Output("scenario-id-store", "data"),
        Output("operator-state-store", "data"),
        Output("network-graph", "elements", allow_duplicate=True),
        Output("network-graph", "stylesheet", allow_duplicate=True),
        Output("graph-empty-state", "style"),
        Output("cascade-log", "children"),
        Output("affected-count", "children"),
        Output("gantt-chart", "figure"),
        Output("summary-metrics", "children"),
        Output("recovery-cards", "children"),
        Output("recovery-status-badge", "children"),
        Output("recovery-comparison-strip", "children"),
        Output("operator-state-badge", "children"),
        Output("workflow-activity-note", "children"),
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
        empty_recovery = empty_recovery_cards()
        empty_comparison = empty_comparison_strip()
        awaiting_state = {"state": "AWAITING CASCADE"}

        if triggered == "reset-btn":
            return (
                None,
                None,
                awaiting_state,
                empty_graph_elements,
                cyto_stylesheet,
                {"display": "flex"},
                empty_log(),
                "0 AFFECTED",
                build_gantt(df, None, COLORS),
                html.Div(),
                empty_recovery,
                "AWAITING CASCADE",
                empty_comparison,
                "AWAITING CASCADE",
                "Scenario reset; audit trail preserved in backend history.",
                html.Div(),
                None,
                None,
            )

        if not flight_id or not delay_min:
            return (
                None,
                None,
                awaiting_state,
                empty_graph_elements,
                cyto_stylesheet,
                {"display": "flex"},
                empty_log(),
                "0 AFFECTED",
                build_gantt(df, None, COLORS),
                html.Div(),
                empty_recovery,
                "AWAITING CASCADE",
                empty_comparison,
                "AWAITING CASCADE",
                "Select a flight and delay to create a replayable scenario.",
                html.Div(),
                None,
                None,
            )

        if platform is not None:
            execution = platform.run_simulation(flight_id, float(delay_min))
            bundle = execution.bundle
            confidence = execution.confidence
            scenario_id = execution.scenario_id
        else:
            bundle = run_simulation_bundle(G, df, flight_id, float(delay_min))
            confidence = None
            scenario_id = None

        operator_state = {"state": "SIMULATED"}
        workflow_note = f"Scenario {scenario_id or 'local'} simulated and stored for review."

        return (
            serialize_cascade_result(bundle.cascade_result, G),
            scenario_id,
            operator_state,
            build_cyto_elements(G, bundle.cascaded_df, flight_id, bundle.affected_ids),
            cyto_stylesheet,
            {"display": "none"},
            build_cascade_log(bundle.cascade_result, COLORS),
            f"{bundle.cascade_result.flights_affected} AFFECTED",
            build_gantt(bundle.cascaded_df, bundle.cascade_result, COLORS),
            build_summary_metrics(bundle.cascade_result, COLORS, confidence=confidence, data_quality=getattr(platform, "data_quality", None)),
            build_recovery_cards(bundle.recovery_options, COLORS),
            f"{len([option for option in bundle.recovery_options if option.feasible])} OPTIONS READY",
            empty_comparison,
            "SIMULATED",
            workflow_note,
            build_optimizer_summary(bundle.optimization, COLORS),
            serialize_recovery_options(bundle.recovery_options),
            None,
        )

    @app.callback(
        Output("cascade-result-store", "data", allow_duplicate=True),
        Output("scenario-id-store", "data", allow_duplicate=True),
        Output("operator-state-store", "data", allow_duplicate=True),
        Output("network-graph", "elements", allow_duplicate=True),
        Output("network-graph", "stylesheet", allow_duplicate=True),
        Output("graph-empty-state", "style", allow_duplicate=True),
        Output("cascade-log", "children", allow_duplicate=True),
        Output("affected-count", "children", allow_duplicate=True),
        Output("gantt-chart", "figure", allow_duplicate=True),
        Output("summary-metrics", "children", allow_duplicate=True),
        Output("recovery-cards", "children", allow_duplicate=True),
        Output("recovery-status-badge", "children", allow_duplicate=True),
        Output("recovery-comparison-strip", "children", allow_duplicate=True),
        Output("operator-state-badge", "children", allow_duplicate=True),
        Output("workflow-activity-note", "children", allow_duplicate=True),
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
        awaiting_state = {"state": "AWAITING CASCADE"}
        return (
            None,
            None,
            awaiting_state,
            empty_graph_elements,
            cyto_stylesheet,
            {"display": "flex"},
            empty_log(),
            "0 AFFECTED",
            build_gantt(df, None, COLORS),
            html.Div(),
            empty_recovery_cards(),
            "AWAITING CASCADE",
            empty_comparison_strip(),
            "AWAITING CASCADE",
            "Active controls changed; previous scenario invalidated to avoid stale decisions.",
            html.Div(),
            None,
            None,
        )

    @app.callback(
        Output("gantt-chart", "figure", allow_duplicate=True),
        Output("network-graph", "elements", allow_duplicate=True),
        Output("selected-recovery-store", "data", allow_duplicate=True),
        Output("recovery-comparison-strip", "children", allow_duplicate=True),
        Output("operator-state-store", "data", allow_duplicate=True),
        Output("operator-state-badge", "children", allow_duplicate=True),
        Output("recovery-status-badge", "children", allow_duplicate=True),
        Output("workflow-activity-note", "children", allow_duplicate=True),
        Input({"type": "recovery-select-btn", "index": ALL}, "n_clicks"),
        State("flight-select", "value"),
        State("delay-slider", "value"),
        State("recovery-options-store", "data"),
        State("cascade-result-store", "data"),
        State("scenario-id-store", "data"),
        prevent_initial_call=True,
    )
    def apply_recovery(_clicks, flight_id, delay_min, recovery_store, cascade_store, scenario_id):
        from dash import ctx

        if not ctx.triggered_id or not flight_id or not recovery_store:
            raise PreventUpdate
        if not cascade_store_matches_request(cascade_store, flight_id, delay_min):
            raise PreventUpdate

        if not isinstance(ctx.triggered_id, dict):
            raise PreventUpdate
        triggered_idx = ctx.triggered_id.get("index", 0)
        selection = select_recovery_option(recovery_store, triggered_idx)
        if selection is None:
            raise PreventUpdate

        if platform is not None and scenario_id:
            platform.record_recovery_selection(
                scenario_id,
                selection.option_payload.get("strategy", "UNKNOWN"),
            )

        state_payload = {
            "state": "RECOMMENDED",
            "selected_strategy": selection.option_payload.get("strategy"),
            "label": selection.option_payload.get("label"),
        }
        workflow_note = f"{selection.option_payload.get('label', 'Recovery plan')} selected; awaiting operator review."

        return (
            build_gantt(selection.recovered_df, None, COLORS, recovery_label=selection.option_payload.get("label")),
            build_cyto_elements(G, selection.recovered_df, flight_id, selection.affected_ids),
            selection.selected_store,
            build_comparison_strip(selection.option_payload, COLORS),
            state_payload,
            "RECOMMENDED",
            recovery_status_badge_text("RECOMMENDED", True, True),
            workflow_note,
        )

    @app.callback(
        Output("operator-state-store", "data", allow_duplicate=True),
        Output("operator-state-badge", "children", allow_duplicate=True),
        Output("recovery-status-badge", "children", allow_duplicate=True),
        Output("workflow-activity-note", "children", allow_duplicate=True),
        Input("mark-reviewed-btn", "n_clicks"),
        Input("accept-plan-btn", "n_clicks"),
        Input("override-plan-btn", "n_clicks"),
        State("scenario-id-store", "data"),
        State("selected-recovery-store", "data"),
        prevent_initial_call=True,
    )
    def update_workflow_state(review_clicks, accept_clicks, override_clicks, scenario_id, selected_recovery_store):
        from dash import ctx

        if not ctx.triggered_id or not scenario_id:
            raise PreventUpdate

        selected_payload = {}
        if selected_recovery_store:
            try:
                selected_payload = json.loads(selected_recovery_store)
            except (TypeError, json.JSONDecodeError):
                selected_payload = {}

        if ctx.triggered_id == "mark-reviewed-btn":
            state = "REVIEWED"
            note = f"Scenario reviewed with plan {selected_payload.get('label', 'baseline')}."
        elif ctx.triggered_id == "accept-plan-btn":
            state = "ACCEPTED"
            note = f"Operator accepted {selected_payload.get('label', 'the no-action baseline')}."
        else:
            state = "OVERRIDDEN"
            note = "Operator override recorded; downstream execution should be confirmed externally."

        if platform is not None:
            platform.record_workflow_transition(scenario_id, state, note=note)

        return (
            {"state": state, **selected_payload},
            state,
            recovery_status_badge_text(state, bool(selected_payload.get("strategy")), True),
            note,
        )

    @app.callback(
        Output("recovery-cards", "children", allow_duplicate=True),
        Output("mark-reviewed-btn", "disabled"),
        Output("accept-plan-btn", "disabled"),
        Output("override-plan-btn", "disabled"),
        Output("operator-state-badge", "className"),
        Output("recovery-status-badge", "className"),
        Output("pdf-export-btn", "disabled"),
        Input("recovery-options-store", "data"),
        Input("selected-recovery-store", "data"),
        Input("operator-state-store", "data"),
        Input("cascade-result-store", "data"),
        prevent_initial_call=True,
    )
    def sync_frontend_state(recovery_store, selected_recovery_store, operator_state_store, cascade_store):
        selected_strategy = parse_selected_strategy(selected_recovery_store)
        state = (
            operator_state_store.get("state")
            if isinstance(operator_state_store, dict)
            else "AWAITING CASCADE"
        )
        has_options = bool(recovery_store)
        has_selection = bool(selected_strategy)
        cards = build_recovery_cards_from_store(recovery_store, COLORS, selected_recovery_store)
        mark_disabled, accept_disabled, override_disabled = workflow_button_states(state, has_selection)
        return (
            cards,
            mark_disabled,
            accept_disabled,
            override_disabled,
            workflow_state_badge_class(state),
            recovery_status_badge_class(state, has_selection, has_options),
            not bool(cascade_store),
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

