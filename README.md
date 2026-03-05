# SILSILA

SILSILA is an interactive disruption-cascade simulator for Hamad International Airport (DOH/OTHH).
It models how a delayed flight can propagate through aircraft rotations, crew dependencies, and passenger connections, then compares simple recovery options and Monte Carlo risk outcomes in a Dash dashboard.

This is a genuine simulation project with real code, tests, and a coherent model pipeline. It is not a production airline optimizer and it does not claim airline-certified operational fidelity.

## What The Project Actually Does

- Loads a daily schedule, using a synthetic Doha hub schedule by default and an OpenSky-based path when enabled.
- Builds a directed dependency graph across flights.
- Simulates delay propagation with edge-specific rules for:
  - aircraft rotation
  - crew transfer
  - passenger connection misses
- Evaluates three recovery heuristics:
  - aircraft swap
  - compress and absorb
  - cancel and rebook
- Runs Monte Carlo scenarios to estimate network-wide disruption risk.
- Exports a PDF summary of the current scenario.

## What It Does Not Claim

- It does not use proprietary Qatar Airways operational systems or internal OTP data.
- It does not solve a formal optimization problem.
- It does not model every airline constraint such as maintenance routing, slot controls, full crew legality, curfews, gate conflicts, or revenue management.
- It should be treated as a systems-engineering simulation and decision-support prototype, not a dispatch-certified ops tool.

## Current Status

Implemented:

- interactive Dash UI
- dependency graph construction
- cascade simulation engine
- recovery heuristics
- Monte Carlo analysis
- PDF export
- regression tests for core behaviors

Recently improved:

- outbound-trigger recovery correctness
- preservation of crew residual effects in recovery strategies
- more state-driven export behavior
- callback state serialization
- stronger graph and schedule behavior tests
- callback code split by feature area

## Architecture

```text
doha_cascade/
├── app.py
├── engine/
│   ├── data_loader.py
│   ├── graph_builder.py
│   ├── cascade.py
│   ├── recovery.py
│   ├── monte_carlo.py
│   ├── pdf_report.py
│   └── cyto_graph.py
├── ui/
│   ├── layout.py
│   ├── callbacks.py
│   ├── callbacks_core.py
│   ├── callbacks_phase3.py
│   └── session_state.py
├── assets/
│   └── style.css
└── tests/
    └── test_smoke.py
```

## Model Assumptions

The project is only as credible as its assumptions. The main ones are explicit:

- Schedule data:
  synthetic schedule is the default reliable path
  OpenSky support is best treated as optional and partial
- Rotations:
  one inbound and one outbound pairing per aircraft in the synthetic schedule
- Crew:
  crew dependencies are simplified into shared crew IDs and transfer windows
- Passenger connections:
  connection demand is estimated heuristically rather than sourced from PNR data
- Recovery:
  swap, compress, and cancel are heuristics, not an optimization solver
- Monte Carlo:
  initial delays are sampled from a configured lognormal distribution calibrated as an approximation, not a validated Doha-specific empirical fit

These assumptions are acceptable for a portfolio-grade simulation if they are stated plainly.

## Why The Project Is Defensible

- The codebase has real module boundaries instead of one-file demo logic.
- Core behaviors are test-covered.
- The UI is backed by an actual dependency graph and propagation engine.
- Recovery output and exports now rely more directly on stored state instead of loosely recomputing everything.
- Limitations are explicit rather than hidden.

## Setup

### Windows PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

### macOS / Linux

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:8050`.

## How To Use

1. Select a trigger flight.
2. Choose a delay magnitude.
3. Run the cascade simulation.
4. Inspect:
   - network graph highlights
   - cascade event log
   - Gantt timeline
   - recovery option cards
5. Run Monte Carlo to inspect network risk.
6. Export a PDF report for the current scenario.

## Test Suite

Run:

```bash
pytest -q
```

The current test suite covers:

- schedule schema sanity
- graph edge-type presence and rotation slack correctness
- cascade schedule updates for inbound and outbound triggers
- recovery ranking and recovery regressions
- Monte Carlo output shape
- PDF generation smoke path
- session-state serialization helpers

## Key Files

- [`app.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/app.py): application entry point
- [`engine/cascade.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/cascade.py): propagation logic
- [`engine/recovery.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/recovery.py): recovery heuristics
- [`engine/monte_carlo.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/monte_carlo.py): risk simulation
- [`ui/callbacks_core.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/callbacks_core.py): live simulation and recovery callbacks
- [`ui/callbacks_phase3.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/callbacks_phase3.py): Monte Carlo and export callbacks
- [`ui/session_state.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/session_state.py): Dash store serialization helpers

## If I Were Presenting This

The strongest accurate description is:

`A systems-engineering simulation of airline disruption propagation at a hub, with interactive recovery heuristics and Monte Carlo risk analysis.`

That is strong, credible, and technically defensible.
