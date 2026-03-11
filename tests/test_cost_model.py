from __future__ import annotations

from datetime import datetime, timezone

from engine.cascade import run_cascade
from engine.cost_model import (
    CALIBRATED_AIRCRAFT_DELAY_COST_USD_PER_MIN,
    CALIBRATED_PASSENGER_DELAY_COST_USD_PER_MIN,
    CancellationCostBreakdown,
    aircraft_delay_cost_per_minute_usd,
    cancellation_cost_breakdown_usd,
    passenger_delay_cost_per_minute_usd,
    passenger_rights_coverage,
)
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph
from engine.recovery import evaluate_all_recovery_options


def test_calibrated_delay_costs_are_exposed_consistently():
    assert aircraft_delay_cost_per_minute_usd() == CALIBRATED_AIRCRAFT_DELAY_COST_USD_PER_MIN
    assert passenger_delay_cost_per_minute_usd() == CALIBRATED_PASSENGER_DELAY_COST_USD_PER_MIN
    assert aircraft_delay_cost_per_minute_usd() > 190.0
    assert passenger_delay_cost_per_minute_usd() > 1.1


def test_cancellation_cost_curve_interpolates_for_widebody_seat_counts():
    breakdown = cancellation_cost_breakdown_usd(355)

    assert isinstance(breakdown, CancellationCostBreakdown)
    assert breakdown.total_usd > 120_000
    assert breakdown.passenger_care_comp_usd > 60_000
    assert breakdown.operational_base_usd > 60_000
    assert breakdown.total_usd == round(breakdown.passenger_care_comp_usd + breakdown.operational_base_usd, 2)


def test_passenger_rights_scope_depends_on_departure_airport():
    uk_leg = passenger_rights_coverage("EGLL", "OTHH")
    doha_leg = passenger_rights_coverage("OTHH", "LFPG")
    eu_leg = passenger_rights_coverage("LFPG", "OTHH")

    assert uk_leg.scheme == "UK261"
    assert uk_leg.eligible
    assert uk_leg.amount_per_pax_usd > 600.0

    assert eu_leg.scheme == "EU261"
    assert eu_leg.eligible
    assert eu_leg.amount_per_pax_usd > 600.0

    assert doha_leg.scheme == "NONE"
    assert not doha_leg.eligible
    assert doha_leg.amount_per_pax_usd == 0.0


def test_cancel_heuristic_removes_the_entire_multihop_chain():
    schedule_df = load_schedule(datetime(2026, 3, 11, tzinfo=timezone.utc), use_opensky=False)
    dependency_graph = build_graph(schedule_df)
    result = run_cascade(dependency_graph, "QR007", 90.0)
    options = {option.strategy: option for option in evaluate_all_recovery_options(dependency_graph, schedule_df, result)}

    cancel = options["CANCEL"]
    residual_ids = {event.flight_id for event in cancel.residual_events}

    assert cancel.feasible
    assert cancel.direct_cost_usd > 100_000
    assert cancel.delay_reduction_min >= 170.0
    assert {"QR008", "QR107", "QR108"}.isdisjoint(residual_ids)
    assert any("Passenger-rights regime: no EU/UK statutory compensation exposure" in line for line in cancel.action_log)
