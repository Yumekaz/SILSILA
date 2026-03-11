# Cost Calibration

This repository now uses a documented cost-calibration layer instead of freehand economics.

## Calibration Snapshot

Capture date: 10 March 2026

Primary sources:
- EUROCONTROL Standard Inputs for Economic Analyses, Edition 10
- European Central Bank reference exchange rates
- EUR-Lex Regulation (EC) No 261/2004
- UK Civil Aviation Authority cancellation-compensation guidance

## Operational Delay Cost

SILSILA uses the EUROCONTROL at-gate tactical delay cost with network effect as the aircraft operating-cost proxy.

- Source value: EUR 166.0 per minute
- FX conversion: 1 EUR = 1.1641 USD
- Model value: USD 193.24 per minute

This value is exposed through `engine.cost_model.aircraft_delay_cost_per_minute_usd()` and mapped into `engine.config.COST_AIRCRAFT_PER_MIN`.

## Passenger Delay Cost

SILSILA uses EUROCONTROL passenger value of time as a passenger-impact proxy.

- Source value: EUR 61.6 per hour
- FX conversion: 1 EUR = 1.1641 USD
- Model value: USD 1.1951 per passenger-minute

This is not a pure airline ledger cost. It is a systems-impact proxy for passenger delay disutility.

## Cancellation Cost

SILSILA now uses the EUROCONTROL traditional network-carrier cancellation cost curve instead of a flat per-passenger rebooking assumption.

Seat-bucket anchors used in the model:

| Seats | Total Cost (EUR) | Passenger Care and Compensation (EUR) |
|---|---:|---:|
| 50 | 6,790 | 3,100 |
| 120 | 16,640 | 7,600 |
| 180 | 25,720 | 12,400 |
| 250 | 85,570 | 40,500 |
| 400 | 123,900 | 64,800 |

For intermediate seat counts, SILSILA uses linear interpolation. For seat counts above 400, it uses a linear extrapolation from the top two wide-body points.

The calibrated implementation lives in [`engine/cost_model.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/cost_model.py).

## Passenger-Rights Scope

The live cancellation heuristic no longer hardcodes a universal EU261 payment.

Instead, SILSILA now:
- estimates direct cancellation cost from the EUROCONTROL seat-bucket curve
- tracks whether a leg would fall under EU261 or UK261 based on departure airport scope
- logs the indicative statutory amount when the disrupted leg is within scope and exceeds the 180-minute trigger

This is more defensible than applying a flat compensation amount to every cancellation, especially for non-EU departures.

## Remaining Limits

The economics are much stronger than before, but not fully closed:
- cancellation cost is still a calibrated benchmark, not Qatar Airways internal finance data
- route-level reprotection, hotel, and compensation are not yet modeled from an airline-specific dataset
- public data still cannot validate true downstream commercial losses flight by flight

## Source Links

- EUROCONTROL Standard Inputs: https://www.eurocontrol.int/publication/standard-inputs-economic-analyses
- ECB exchange rates: https://www.ecb.europa.eu/stats/eurofxref/
- EUR-Lex 261/2004: https://eur-lex.europa.eu/eli/reg/2004/261/oj/eng
- UK CAA cancellations guidance: https://www.caa.co.uk/passengers/resolving-travel-problems/delays-and-cancellations/cancellations/
