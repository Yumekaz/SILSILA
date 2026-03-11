"""
historical_validation.py
------------------------
External-case benchmark harness for the synthetic DOH disruption model.

The simulator does not recreate the exact published Qatar Airways schedules,
so each public reference case is mapped to an in-model analog leg with a
similar haul length and bank role. The suite then checks whether the modeled
cascade lands inside documented tolerance bands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

import pandas as pd

from engine.cascade import run_cascade
from engine.data_loader import load_schedule
from engine.graph_builder import build_graph


@dataclass(frozen=True)
class MetricBand:
    lower: float
    upper: float

    def contains(self, value: float) -> bool:
        return self.lower <= value <= self.upper

    def label(self) -> str:
        lower = int(self.lower) if float(self.lower).is_integer() else round(self.lower, 1)
        upper = int(self.upper) if float(self.upper).is_integer() else round(self.upper, 1)
        return f"{lower}-{upper}"


@dataclass(frozen=True)
class HistoricalValidationCase:
    case_id: str
    public_reference: str
    public_source_url: str
    observed_signal: str
    analog_trigger_id: str
    analog_rationale: str
    trigger_delay_min: float
    expectation: str
    flights_affected_band: MetricBand | None = None
    total_delay_band: MetricBand | None = None
    cascade_depth_band: MetricBand | None = None
    stranded_pax_band: MetricBand | None = None
    critical_count_band: MetricBand | None = None
    required_edge_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationCheck:
    metric: str
    expected: str
    observed: str
    passed: bool


@dataclass
class HistoricalValidationCaseResult:
    case: HistoricalValidationCase
    trigger_id: str
    summary: dict[str, Any]
    edge_types: tuple[str, ...]
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def score_pct(self) -> float:
        if not self.checks:
            return 0.0
        passed_checks = sum(1 for check in self.checks if check.passed)
        return round((passed_checks / len(self.checks)) * 100.0, 1)

    def to_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "public_reference": self.case.public_reference,
            "analog_trigger_id": self.trigger_id,
            "trigger_delay_min": self.case.trigger_delay_min,
            "flights_affected": self.summary["flights_affected"],
            "total_delay_min": round(self.summary["total_delay_min"], 1),
            "total_pax_stranded": self.summary["total_pax_stranded"],
            "cascade_depth": self.summary["cascade_depth"],
            "critical_count": self.summary["critical_count"],
            "edge_types": ", ".join(self.edge_types),
            "passed": self.passed,
            "score_pct": self.score_pct,
        }


@dataclass
class HistoricalValidationSuiteResult:
    case_results: list[HistoricalValidationCaseResult]

    @property
    def passed_cases(self) -> int:
        return sum(1 for result in self.case_results if result.passed)

    @property
    def total_cases(self) -> int:
        return len(self.case_results)

    @property
    def pass_rate_pct(self) -> float:
        if not self.case_results:
            return 0.0
        return round((self.passed_cases / self.total_cases) * 100.0, 1)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([result.to_row() for result in self.case_results])


HISTORICAL_VALIDATION_CASES: tuple[HistoricalValidationCase, ...] = (
    HistoricalValidationCase(
        case_id="HV-01",
        public_reference="FlightStats QR702 JFK-DOH (Aug-Oct 2025)",
        public_source_url="https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/702",
        observed_signal="Public OTP profile shows roughly 33 min average arrival delay into Doha.",
        analog_trigger_id="QR021",
        analog_rationale="QR021 is the synthetic JFK inbound and the closest long-haul bank-feed analog in the model.",
        trigger_delay_min=33.0,
        expectation="Moderate inbound JFK lateness should produce a small but non-zero downstream hub-wave cascade.",
        flights_affected_band=MetricBand(2, 3),
        total_delay_band=MetricBand(20, 35),
        cascade_depth_band=MetricBand(1, 2),
        stranded_pax_band=MetricBand(20, 30),
        required_edge_types=("PAX_CNXN", "ROTATION"),
    ),
    HistoricalValidationCase(
        case_id="HV-02",
        public_reference="FlightStats QR777 DOH-MIA high-variance profile (Jun-Jul 2025)",
        public_source_url="https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/777/DOH",
        observed_signal="Public route profile shows a much heavier tail, with average delay near 58 min.",
        analog_trigger_id="QR021",
        analog_rationale="The JFK inbound remains the best available long-haul analog for a severe-haul disruption day.",
        trigger_delay_min=58.0,
        expectation="A severe long-haul inbound event should break through the first turn and reach later legs in the rotation chain.",
        flights_affected_band=MetricBand(4, 6),
        total_delay_band=MetricBand(60, 90),
        cascade_depth_band=MetricBand(2, 4),
        stranded_pax_band=MetricBand(40, 60),
        required_edge_types=("PAX_CNXN", "ROTATION"),
    ),
    HistoricalValidationCase(
        case_id="HV-03",
        public_reference="FlightStats QR127 DOH-MXP lower-delay baseline (Nov-Dec 2025)",
        public_source_url="https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/127/DOH",
        observed_signal="Public route profile sits in a materially lower-delay regime, around 15 min average delay.",
        analog_trigger_id="QR548",
        analog_rationale="QR548 is the shortest-haul inbound in the synthetic bank and provides the cleanest low-risk baseline contrast.",
        trigger_delay_min=15.0,
        expectation="A low-delay short-haul baseline should create little to no downstream cascade.",
        flights_affected_band=MetricBand(0, 1),
        total_delay_band=MetricBand(0, 10),
        cascade_depth_band=MetricBand(0, 1),
        stranded_pax_band=MetricBand(0, 0),
    ),
    HistoricalValidationCase(
        case_id="HV-04",
        public_reference="FlightStats QR737 DOH-SFO heavy-tail route (Aug-Sep 2025)",
        public_source_url="https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/737/DOH",
        observed_signal="Public OTP profile shows a heavy tail around a 40 min average delay regime.",
        analog_trigger_id="QR842",
        analog_rationale="QR842 is a longer-haul widebody inbound whose outbound chain is driven mainly by aircraft rotation.",
        trigger_delay_min=40.0,
        expectation="A widebody heavy-tail case should produce a contained two-hop aircraft-rotation cascade without major missed-connection spill.",
        flights_affected_band=MetricBand(2, 3),
        total_delay_band=MetricBand(30, 45),
        cascade_depth_band=MetricBand(2, 3),
        stranded_pax_band=MetricBand(0, 0),
        required_edge_types=("ROTATION",),
    ),
    HistoricalValidationCase(
        case_id="HV-05",
        public_reference="Business Insider / Flightradar24 QR36 crew-delay incident (2024-01-04)",
        public_source_url="https://www.businessinsider.com/qatar-airways-pilot-crew-stuck-in-elevator-over-3-hours-2024-1",
        observed_signal="Public reporting describes an approximately four-hour crew-driven disruption.",
        analog_trigger_id="QR068",
        analog_rationale="QR068 is a European inbound whose synthetic crew pairing can spill across crew, connection, and rotation dependencies.",
        trigger_delay_min=240.0,
        expectation="A four-hour crew event should create a deep multi-channel cascade with critical downstream legs.",
        flights_affected_band=MetricBand(5, 7),
        total_delay_band=MetricBand(600, 750),
        cascade_depth_band=MetricBand(3, 4),
        stranded_pax_band=MetricBand(35, 55),
        critical_count_band=MetricBand(2, 4),
        required_edge_types=("CREW", "PAX_CNXN", "ROTATION"),
    ),
)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.1f}"
    return str(value)


def _range_check(metric: str, value: float, band: MetricBand | None) -> ValidationCheck | None:
    if band is None:
        return None
    return ValidationCheck(
        metric=metric,
        expected=band.label(),
        observed=_format_value(value),
        passed=band.contains(value),
    )


def _edge_type_check(edge_types: tuple[str, ...], required: tuple[str, ...]) -> ValidationCheck | None:
    if not required:
        return None
    observed = ", ".join(edge_types) if edge_types else "none"
    expected = ", ".join(required)
    return ValidationCheck(
        metric="edge_types",
        expected=expected,
        observed=observed,
        passed=set(required).issubset(set(edge_types)),
    )


def run_historical_validation_case(
    case: HistoricalValidationCase,
    schedule_df: pd.DataFrame,
    graph=None,
) -> HistoricalValidationCaseResult:
    if case.analog_trigger_id not in set(schedule_df["flight_id"]):
        missing = ValidationCheck(
            metric="trigger_presence",
            expected=case.analog_trigger_id,
            observed="missing",
            passed=False,
        )
        return HistoricalValidationCaseResult(
            case=case,
            trigger_id=case.analog_trigger_id,
            summary={
                "flights_affected": 0,
                "total_delay_min": 0.0,
                "total_pax_stranded": 0,
                "cascade_depth": 0,
                "critical_count": 0,
            },
            edge_types=(),
            checks=[missing],
        )

    graph = graph if graph is not None else build_graph(schedule_df)
    cascade = run_cascade(graph, case.analog_trigger_id, case.trigger_delay_min)
    summary = cascade.summary()
    edge_types = tuple(sorted({event.edge_type for event in cascade.events}))

    checks = [
        check
        for check in (
            _range_check("flights_affected", float(summary["flights_affected"]), case.flights_affected_band),
            _range_check("total_delay_min", float(summary["total_delay_min"]), case.total_delay_band),
            _range_check("cascade_depth", float(summary["cascade_depth"]), case.cascade_depth_band),
            _range_check("total_pax_stranded", float(summary["total_pax_stranded"]), case.stranded_pax_band),
            _range_check("critical_count", float(summary["critical_count"]), case.critical_count_band),
            _edge_type_check(edge_types, case.required_edge_types),
        )
        if check is not None
    ]

    return HistoricalValidationCaseResult(
        case=case,
        trigger_id=case.analog_trigger_id,
        summary=summary,
        edge_types=edge_types,
        checks=checks,
    )


def run_historical_validation_suite(
    schedule_df: pd.DataFrame | None = None,
    graph=None,
    cases: Sequence[HistoricalValidationCase] | None = None,
    date: datetime | None = None,
) -> HistoricalValidationSuiteResult:
    if schedule_df is None:
        benchmark_date = date or datetime(2026, 3, 11, tzinfo=timezone.utc)
        schedule_df = load_schedule(benchmark_date, use_opensky=False)
    if graph is None:
        graph = build_graph(schedule_df)

    suite_cases = tuple(cases or HISTORICAL_VALIDATION_CASES)
    return HistoricalValidationSuiteResult(
        case_results=[
            run_historical_validation_case(case, schedule_df=schedule_df, graph=graph)
            for case in suite_cases
        ]
    )
