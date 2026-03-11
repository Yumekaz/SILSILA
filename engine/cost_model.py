"""
cost_model.py
-------------
Documented calibration inputs and helper functions for operational cost modeling.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

# Calibration capture date: 10 March 2026.
# Sources are documented in docs/cost_calibration.md.
ECB_EUR_TO_USD = 1.1641
ECB_GBP_PER_EUR = 0.8655
GBP_TO_USD = ECB_EUR_TO_USD / ECB_GBP_PER_EUR

EUROCONTROL_AT_GATE_TACTICAL_DELAY_EUR_PER_MIN = 166.0
EUROCONTROL_PASSENGER_VALUE_EUR_PER_HOUR = 61.6

# Traditional network-carrier cancellation cost curve from EUROCONTROL Standard Inputs Ed. 10.
# The low-cost 189-seat point is intentionally excluded because SILSILA models a hub network carrier.
CANCELLATION_COST_CURVE_EUR = [
    (50, 6790.0, 3100.0),
    (120, 16640.0, 7600.0),
    (180, 25720.0, 12400.0),
    (250, 85570.0, 40500.0),
    (400, 123900.0, 64800.0),
]

EU_AIRPORTS = {"EDDF", "LFPG"}
UK_AIRPORTS = {"EGLL"}
AIRPORT_COORDS = {
    "OTHH": (25.2731, 51.6081),
    "EGLL": (51.4700, -0.4543),
    "KJFK": (40.6413, -73.7781),
    "LFPG": (49.0097, 2.5479),
    "EDDF": (50.0379, 8.5622),
    "VTBS": (13.6900, 100.7501),
    "WSSS": (1.3644, 103.9915),
    "VABB": (19.0896, 72.8656),
    "WMKK": (2.7456, 101.7072),
}


@dataclass(frozen=True)
class CancellationCostBreakdown:
    seats: int
    total_usd: float
    passenger_care_comp_usd: float
    operational_base_usd: float


@dataclass(frozen=True)
class PassengerRightsCoverage:
    scheme: str
    eligible: bool
    distance_km: float | None
    amount_per_pax_usd: float


def aircraft_delay_cost_per_minute_usd() -> float:
    return round(EUROCONTROL_AT_GATE_TACTICAL_DELAY_EUR_PER_MIN * ECB_EUR_TO_USD, 2)


def passenger_delay_cost_per_minute_usd() -> float:
    hourly_usd = EUROCONTROL_PASSENGER_VALUE_EUR_PER_HOUR * ECB_EUR_TO_USD
    return round(hourly_usd / 60.0, 4)


def cancellation_cost_breakdown_usd(seats: int) -> CancellationCostBreakdown:
    total_eur = _interpolate_curve(seats, index=1)
    passenger_care_eur = _interpolate_curve(seats, index=2)
    total_usd = round(total_eur * ECB_EUR_TO_USD, 2)
    passenger_care_usd = round(passenger_care_eur * ECB_EUR_TO_USD, 2)
    return CancellationCostBreakdown(
        seats=seats,
        total_usd=total_usd,
        passenger_care_comp_usd=passenger_care_usd,
        operational_base_usd=round(total_usd - passenger_care_usd, 2),
    )


def passenger_rights_coverage(origin: str, destination: str, operator_is_eu_carrier: bool = False) -> PassengerRightsCoverage:
    origin = str(origin).upper()
    destination = str(destination).upper()
    distance_km = route_distance_km(origin, destination)
    if distance_km is None:
        return PassengerRightsCoverage(scheme="NONE", eligible=False, distance_km=None, amount_per_pax_usd=0.0)

    if origin in EU_AIRPORTS:
        return PassengerRightsCoverage(
            scheme="EU261",
            eligible=True,
            distance_km=distance_km,
            amount_per_pax_usd=round(_eu261_compensation_eur(distance_km) * ECB_EUR_TO_USD, 2),
        )

    if origin in UK_AIRPORTS:
        return PassengerRightsCoverage(
            scheme="UK261",
            eligible=True,
            distance_km=distance_km,
            amount_per_pax_usd=round(_uk261_compensation_gbp(distance_km) * GBP_TO_USD, 2),
        )

    if destination in EU_AIRPORTS and operator_is_eu_carrier:
        return PassengerRightsCoverage(
            scheme="EU261",
            eligible=True,
            distance_km=distance_km,
            amount_per_pax_usd=round(_eu261_compensation_eur(distance_km) * ECB_EUR_TO_USD, 2),
        )

    return PassengerRightsCoverage(scheme="NONE", eligible=False, distance_km=distance_km, amount_per_pax_usd=0.0)


def route_distance_km(origin: str, destination: str) -> float | None:
    origin_coords = AIRPORT_COORDS.get(str(origin).upper())
    destination_coords = AIRPORT_COORDS.get(str(destination).upper())
    if origin_coords is None or destination_coords is None:
        return None

    lat1, lon1 = origin_coords
    lat2, lon2 = destination_coords
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return round(2 * radius_km * asin(sqrt(a)), 1)


CALIBRATED_AIRCRAFT_DELAY_COST_USD_PER_MIN = aircraft_delay_cost_per_minute_usd()
CALIBRATED_PASSENGER_DELAY_COST_USD_PER_MIN = passenger_delay_cost_per_minute_usd()


def _interpolate_curve(seats: int, index: int) -> float:
    ordered = sorted(CANCELLATION_COST_CURVE_EUR, key=lambda point: point[0])
    if seats <= ordered[0][0]:
        return ordered[0][index]
    if seats >= ordered[-1][0]:
        x0, y0 = ordered[-2][0], ordered[-2][index]
        x1, y1 = ordered[-1][0], ordered[-1][index]
        slope = (y1 - y0) / (x1 - x0)
        return y1 + slope * (seats - x1)

    for lower, upper in zip(ordered, ordered[1:]):
        if lower[0] <= seats <= upper[0]:
            x0, y0 = lower[0], lower[index]
            x1, y1 = upper[0], upper[index]
            slope = (y1 - y0) / (x1 - x0)
            return y0 + slope * (seats - x0)

    return ordered[-1][index]


def _eu261_compensation_eur(distance_km: float) -> float:
    if distance_km <= 1500:
        return 250.0
    if distance_km <= 3500:
        return 400.0
    return 600.0


def _uk261_compensation_gbp(distance_km: float) -> float:
    if distance_km <= 1500:
        return 220.0
    if distance_km <= 3500:
        return 350.0
    return 520.0
