# Historical Validation

This repo still does not contain a completed downstream-cascade validation package, but it now includes a public case inventory and a validation structure.

## Current State

- The code supports an OpenSky-based path.
- The default operational path remains the synthetic schedule because it is complete and reliable for graph construction.
- Public source inventory is included below.
- Full expected-vs-actual cascade validation is still pending because downstream airline-internal outcomes are not publicly available in sufficient detail.

## Public Case Inventory

These public cases can be used as calibration anchors for delay realism and disruption narratives:

| Case ID | Public Source | Flight / Context | Publicly Observable Signal |
|---|---|---|---|
| HV-01 | FlightStats | QR701 DOH-JFK | Average delay profile and poor OTP window for Feb-Mar 2025 |
| HV-02 | FlightStats | QR702 JFK-DOH | Arrival delay distribution for Aug-Oct 2025 |
| HV-03 | FlightStats | QR777 DOH-MIA | High-variance delay profile despite strong on-time percentage |
| HV-04 | FlightStats | QR127 DOH-MXP | Lower-delay route for contrast/baseline |
| HV-05 | FlightStats | QR737 DOH-SFO | Route with heavy-tail delay characteristics |
| HV-06 | Business Insider / Flightradar24 reference | QR36 Birmingham-Doha crew-delay incident | Publicly reported ~4 hour departure disruption caused by crew access failure |

## Validation Table Template

| Case ID | Date Range / Date | Trigger Flight | Observed Delay Signal | Expected Downstream Impact Hypothesis | Model Output | Within Tolerance |
|---|---|---|---|---|---|---|
| HV-01 | Feb-Mar 2025 | QR701 | Poor OTP, avg delay ~34 min | Long-haul inbound trigger should stress high-value outbound bank | TBD | TBD |
| HV-02 | Aug-Oct 2025 | QR702 | Avg arrival delay ~33 min | Inbound lateness to Doha should test hub-wave propagation | TBD | TBD |
| HV-03 | Jun-Jul 2025 | QR777 | Avg delay ~58 min, high variance | Rare but severe trigger case | TBD | TBD |
| HV-04 | Nov-Dec 2025 | QR127 | Avg delay ~15 min | Lower-risk baseline case | TBD | TBD |
| HV-05 | Aug-Sep 2025 | QR737 | Avg delay ~40 min, heavy tail | Long-haul cascade stress case | TBD | TBD |
| HV-06 | 2024-01-04 | QR36 | Publicly reported ~4 hour delay | Crew-driven disruption narrative | TBD | TBD |

## Source Links

- FlightStats QR701: https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/701/DOH
- FlightStats QR702: https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/702
- FlightStats QR777: https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/777/DOH
- FlightStats QR127: https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/127/DOH
- FlightStats QR737: https://www.flightstats.com/v2/flight-ontime-performance-rating/QR/737/DOH
- Business Insider QR36 incident: https://www.businessinsider.com/qatar-airways-pilot-crew-stuck-in-elevator-over-3-hours-2024-1

## What Is Still Missing

- verified downstream connection misses, crew illegality events, or aircraft knock-on effects for these public cases
- tolerance-based pass/fail comparison against a trusted operational reference
