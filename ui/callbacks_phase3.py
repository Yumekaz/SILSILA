"""
callbacks_phase3.py
-------------------
Monte Carlo analysis and PDF export callbacks.
"""

from __future__ import annotations

from dash import Input, Output, State, dcc
from dash.exceptions import PreventUpdate

from engine.config import MC_SCENARIOS
from engine.monte_carlo import run_monte_carlo
from engine.sensitivity import run_turnaround_sensitivity
from ui.analysis_views import build_monte_carlo_outputs, build_sensitivity_outputs
from ui.callbacks_core import COLORS
from ui.workflows import prepare_pdf_export_bundle



def register_phase3_callbacks(app, G, df, platform=None):
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

        mc = platform.run_monte_carlo_sync(n_scenarios=MC_SCENARIOS) if platform is not None else run_monte_carlo(G, df, n_scenarios=MC_SCENARIOS)
        return build_monte_carlo_outputs(mc, G, COLORS)

    @app.callback(
        Output("sensitivity-status-bar", "children"),
        Output("sensitivity-chart", "figure"),
        Output("sensitivity-summary", "children"),
        Input("sensitivity-run-btn", "n_clicks"),
        State("flight-select", "value"),
        State("delay-slider", "value"),
        prevent_initial_call=True,
    )
    def run_sensitivity(n_clicks, flight_id, delay_min):
        if not n_clicks or not flight_id or not delay_min:
            raise PreventUpdate

        if platform is not None:
            points = platform.run_sensitivity_sync(flight_id=flight_id, delay_min=float(delay_min))
        else:
            points = run_turnaround_sensitivity(
                df,
                trigger_ids=[flight_id],
                trigger_delay_min=float(delay_min),
                min_turnaround_values=[35.0, 45.0, 55.0, 65.0],
            )
        return build_sensitivity_outputs(points, flight_id, float(delay_min), COLORS)

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

        if platform is not None:
            pdf_bytes, filename = platform.generate_pdf_bytes(
                flight_id=flight_id,
                delay_min=float(delay_min),
                cascade_store=cascade_store,
                recovery_store=recovery_store,
                selected_recovery_store=selected_recovery_store,
                mc_store=mc_store,
            )
            return dcc.send_bytes(pdf_bytes, filename=filename)

        export_bundle = prepare_pdf_export_bundle(
            G,
            df,
            flight_id,
            float(delay_min),
            cascade_store,
            recovery_store,
            selected_recovery_store,
        )
        mc = run_monte_carlo(G, df, n_scenarios=MC_SCENARIOS)
        from engine.pdf_report import generate_pdf_report
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            path = tmp.name
        generate_pdf_report(export_bundle.cascade_payload, export_bundle.recovery_payload, mc, path)
        with open(path, "rb") as handle:
            pdf_bytes = handle.read()
        os.unlink(path)

        filename = (
            f"SILSILA_{flight_id}_{int(delay_min)}min_"
            f"{export_bundle.cascade_payload.get('flights_affected', 0)}affected.pdf"
        )
        return dcc.send_bytes(pdf_bytes, filename=filename)
