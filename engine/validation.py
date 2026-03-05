"""
validation.py
-------------
Internal schedule and graph validation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from engine.data_loader import REQUIRED_COLUMNS


@dataclass
class ValidationReport:
    passed: bool
    errors: list[str]
    warnings: list[str]


def validate_schedule(df: pd.DataFrame) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    missing = sorted(REQUIRED_COLUMNS.difference(df.columns))
    if missing:
        errors.append(f"Missing columns: {', '.join(missing)}")
        return ValidationReport(False, errors, warnings)

    if df.empty:
        errors.append("Schedule is empty.")

    if df["flight_id"].duplicated().any():
        errors.append("Duplicate flight_id values found.")

    if not (df["direction"] == "inbound").any():
        errors.append("No inbound flights available.")
    if not (df["direction"] == "outbound").any():
        errors.append("No outbound flights available.")

    if (df["pax"] < 0).any():
        errors.append("Negative passenger counts found.")

    if df["turnaround_slack_min"].lt(-180).any():
        warnings.append("Very negative turnaround slack found; schedule may be inconsistent.")

    return ValidationReport(not errors, errors, warnings)


def validate_graph(graph) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    if graph.number_of_nodes() == 0:
        errors.append("Graph has no nodes.")
    if graph.number_of_edges() == 0:
        errors.append("Graph has no edges.")

    edge_types = {data.get("edge_type") for _, _, data in graph.edges(data=True)}
    for required in ("ROTATION", "CREW", "PAX_CNXN"):
        if required not in edge_types:
            warnings.append(f"Graph missing edge type: {required}")

    return ValidationReport(not errors, errors, warnings)
