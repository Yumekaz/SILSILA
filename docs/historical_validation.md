# Historical Validation

The repo now includes a reproducible external-case validation harness in `engine/historical_validation.py`.

It still does **not** claim airline-internal ground truth. What it now does claim, honestly, is stronger than before:

- five public disruption references are encoded in-repo as benchmark cases
- each public case is mapped to a synthetic analog leg with a stated rationale
- the simulator is scored against tolerance bands for cascade size, delay, depth, stranded passengers, and dependency channels
- the benchmark is regression-tested so future model changes can be checked against the same external cases

## How The Mapping Works

The synthetic DOH schedule does not reproduce the exact published Qatar Airways flight numbers and timestamps, so validation is done through **analog mapping**.

Each public case records:

- the public source and observable signal
- the synthetic trigger leg chosen as the closest in-model analog
- the trigger delay injected into the simulator
- tolerance bands that define what would count as a realistic modeled response

That keeps the package honest: this is external-case benchmarking against public evidence, not a claim of having the airline's internal downstream event logs.

## Current Benchmark Suite

Reference run: synthetic schedule dated **2026-03-11 UTC**.

| Case ID | Public Reference | Synthetic Analog | Trigger Delay | Tolerance Focus | Current Model Output | Result |
|---|---|---|---:|---|---|---|
| HV-01 | FlightStats QR702 JFK-DOH (Aug-Oct 2025) | QR021 | 33 min | 2-3 flights, 20-35 delay min, 20-30 stranded pax, `PAX_CNXN` + `ROTATION` | 2 flights, 22 delay min, 24 stranded pax, depth 1 | PASS |
| HV-02 | FlightStats QR777 DOH-MIA high-variance profile (Jun-Jul 2025) | QR021 | 58 min | 4-6 flights, 60-90 delay min, depth 2-4 | 5 flights, 71 delay min, 48 stranded pax, depth 3 | PASS |
| HV-03 | FlightStats QR127 DOH-MXP baseline (Nov-Dec 2025) | QR548 | 15 min | near-zero cascade baseline | 0 flights, 0 delay min, 0 stranded pax, depth 0 | PASS |
| HV-04 | FlightStats QR737 DOH-SFO heavy-tail profile (Aug-Sep 2025) | QR842 | 40 min | 2-3 flights, 30-45 delay min, pure rotation-led spill | 2 flights, 34 delay min, 0 stranded pax, depth 2 | PASS |
| HV-05 | Business Insider / Flightradar24 QR36 crew incident (2024-01-04) | QR068 | 240 min | 5-7 flights, 600-750 delay min, 35-55 stranded pax, `CREW` + `PAX_CNXN` + `ROTATION` | 6 flights, 682.7 delay min, 43 stranded pax, depth 3, 3 critical legs | PASS |

## Running The Suite

```python
from engine.historical_validation import run_historical_validation_suite

suite = run_historical_validation_suite()
print(suite.to_frame())
print(suite.pass_rate_pct)
```

Automated coverage lives in `tests/test_historical_validation.py`.

## What This Closes

Compared with the earlier repository state, this closes the biggest validation gap that was still explicitly called out:

- the repo no longer only lists public references; it executes them as a benchmark suite
- validation is no longer purely narrative; it is tolerance-scored and regression-tested
- the model now has a documented external realism check beyond internal consistency tests

## What Still Does Not Exist

Important limits remain:

- no airline-internal downstream truth set for exact missed connections, duty illegality, or swap decisions
- no airport-operations or OCC ground-truth replay package
- analog mapping is still a proxy method, not one-to-one reconstruction of the public flights

That means the simulator is now meaningfully better validated, but it is still not claiming certified operational fidelity.
