from __future__ import annotations

import json

from ui.dashboard_views import (
    build_recovery_cards_from_store,
    parse_selected_strategy,
    recovery_status_badge_text,
    recovery_status_badge_class,
    workflow_button_states,
    workflow_state_badge_class,
)


COLORS = {
    "bg_0": "#06090F",
    "bg_1": "#0C1220",
    "bg_2": "#111B30",
    "bg_3": "#172039",
    "border": "#1C2D48",
    "gold": "#E8A020",
    "cyan": "#00C8FF",
    "teal": "#00D4A0",
    "red": "#FF3D5A",
    "orange": "#FF6B35",
    "text_1": "#E4EBF7",
    "text_2": "#8CA0C0",
    "text_3": "#4A6080",
    "normal": "#2A4A7A",
    "delayed": "#E8A020",
}


def test_workflow_button_states_follow_operator_state():
    assert workflow_button_states("AWAITING CASCADE", False) == (True, True, True)
    assert workflow_button_states("SIMULATED", False) == (True, True, False)
    assert workflow_button_states("SIMULATED", True) == (False, True, False)
    assert workflow_button_states("RECOMMENDED", True) == (False, True, False)
    assert workflow_button_states("REVIEWED", True) == (True, False, False)
    assert workflow_button_states("ACCEPTED", True) == (True, True, True)


def test_status_class_helpers_map_known_states():
    assert workflow_state_badge_class("AWAITING CASCADE").endswith("status-awaiting")
    assert workflow_state_badge_class("SIMULATED").endswith("status-simulated")
    assert recovery_status_badge_class("SIMULATED", False, True).endswith("status-ready")
    assert recovery_status_badge_class("RECOMMENDED", True, True).endswith("status-recommended")
    assert recovery_status_badge_class("OVERRIDDEN", False, True).endswith("status-overridden")
    assert recovery_status_badge_text("RECOMMENDED", True, True) == "PLAN SELECTED"
    assert recovery_status_badge_text("REVIEWED", True, True) == "UNDER REVIEW"


def test_selected_strategy_is_parsed_and_active_card_is_disabled():
    recovery_payload = json.dumps([
        {
            "strategy": "SWAP",
            "label": "AIRCRAFT SWAP",
            "description": "Swap the outbound aircraft.",
            "feasible": True,
            "infeasibility_reason": "",
            "delay_reduction_min": 22,
            "delay_reduction_pct": 64,
            "direct_cost_usd": 8000,
            "net_cost_usd": 5400,
            "pax_saved": 180,
            "pax_stranded": 0,
            "score": 88,
            "pareto_efficient": True,
            "recommendation": "Best trade-off",
            "action_log": ["Swap aircraft", "Reassign stand"],
        }
    ])
    selected_store = json.dumps({"strategy": "SWAP", "label": "AIRCRAFT SWAP"})

    assert parse_selected_strategy(selected_store) == "SWAP"

    cards = build_recovery_cards_from_store(recovery_payload, COLORS, selected_store)
    grid = cards[0]
    card = grid.children[0]
    button = card.children[-1]

    assert "recovery-card-active" in card.className
    assert button.disabled is True
    assert button.children == "ACTIVE PLAN"
