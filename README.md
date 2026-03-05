# SILSILA

SILSILA is a systems-engineering simulation of flight-disruption propagation at Hamad International Airport (DOH/OTHH). It models how an inbound delay can spread through aircraft rotations, simplified crew dependencies, and passenger connections, then compares recovery actions, runs Monte Carlo risk scenarios, and exports a report.

The project is designed as a transparent decision-support prototype. It is not an airline-certified operational optimizer, but it is no longer just a dashboard demo: it contains a graph model, propagation engine, discrete recovery optimizer, sensitivity analysis, regression tests, and a structured documentation package.

## Scope

The system currently supports:

- daily Doha schedule loading
- graph construction across flights and dependencies
- cascade simulation from an inbound trigger
- recovery evaluation for swap, compress/absorb, and cancel actions
- discrete optimization across feasible recovery candidates
- Pareto-front tradeoff analysis
- Monte Carlo network-risk analysis
- turnaround sensitivity analysis
- PDF report export

## Technical Positioning

This repository should be described as:

`A systems-engineering disruption simulator for a hub-and-spoke airline network, with recovery tradeoff analysis, risk simulation, and report generation.`

That is an accurate claim.

## What Makes It More Than A Demo

- Core state lives in explicit schedule, graph, cascade, and recovery models.
- Recovery is no longer ranked only by hand-tuned heuristic score. A discrete optimization layer now minimizes a weighted objective across feasible actions.
- Recovery options also expose Pareto-efficient tradeoffs rather than pretending there is always one obvious best answer.
- Sensitivity analysis is implemented as an actual analysis path, not only as documentation.
- Validation and deployment artifacts exist in the repository.

## Key Features

### 1. Dependency Graph

Flights are modeled as nodes. Edges represent:

- aircraft rotation dependencies
- crew handover dependencies
- passenger connection dependencies

Relevant files:

- [`engine/graph_builder.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/graph_builder.py)
- [`engine/data_loader.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/data_loader.py)

### 2. Cascade Simulation

Given an inbound trigger flight and a delay magnitude, the engine propagates disruption through the dependency graph and computes:

- affected flights
- propagated delay
- stranded passengers
- estimated cost
- propagation depth and path

Relevant file:

- [`engine/cascade.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/cascade.py)

### 3. Recovery Layer

The recovery layer evaluates:

- `SWAP`
- `DELAY`
- `CANCEL`

Each candidate carries:

- residual delay
- net cost
- passenger impact
- action log
- Pareto efficiency tag

Relevant file:

- [`engine/recovery.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/recovery.py)

### 4. Optimization Layer

The repository now includes a discrete optimization step over feasible recovery candidates. The optimizer minimizes a weighted objective across:

- residual net cost
- residual delay
- stranded passengers

This is not a full airline OR solver, but it is a real optimization layer over candidate actions rather than pure score ordering.

Relevant file:

- [`engine/optimizer.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/optimizer.py)

### 5. Monte Carlo Risk Analysis

The app can run multi-scenario disruption analysis and produce:

- cascade cost distribution
- sampled delay distribution
- risk heatmap
- network summary metrics

Relevant file:

- [`engine/monte_carlo.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/monte_carlo.py)

### 6. Sensitivity Analysis

The app includes turnaround sensitivity analysis, showing how cascade severity changes as the assumed minimum turnaround requirement is tightened or relaxed.

Relevant file:

- [`engine/sensitivity.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/sensitivity.py)

### 7. Reporting

The system exports a PDF report covering:

- cascade summary
- recovery comparison
- Monte Carlo summary
- flight risk profiles
- integration note

Relevant file:

- [`engine/pdf_report.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/pdf_report.py)

## User Interface

The dashboard includes:

- inbound trigger selector
- delay input controls
- interactive network graph
- cascade event log
- Gantt schedule view
- recovery cards
- optimizer summary
- Monte Carlo panel
- sensitivity-analysis panel
- PDF export action

Relevant files:

- [`ui/layout.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/layout.py)
- [`ui/callbacks_core.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/callbacks_core.py)
- [`ui/callbacks_phase3.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/callbacks_phase3.py)
- [`ui/session_state.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/ui/session_state.py)

## Data Path

The data path is intentionally explicit:

- OpenSky support exists for public arrival data
- the application still falls back to a synthetic but internally consistent hub schedule when the public data path is incomplete
- schedule provenance is now carried in `DataFrame.attrs["data_source"]` and surfaced in the UI header

This is a pragmatic compromise: the app remains runnable while documenting when it is using a partial public-data path versus a modeled schedule.

## Validation

The repository includes both automated tests and internal validation helpers.

Automated checks currently cover:

- schedule schema and provenance
- schedule validation reports
- graph validation reports
- rotation-edge slack correctness
- cascade propagation behavior
- recovery regressions
- optimizer behavior
- Monte Carlo output shape
- sensitivity-analysis behavior
- PDF generation
- state serialization

Run:

```bash
pytest -q
```

Relevant files:

- [`engine/validation.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/engine/validation.py)
- [`tests/test_smoke.py`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/tests/test_smoke.py)

## Documentation Package

The repository includes a dedicated engineering documentation set under [`docs/`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs):

- [`requirements.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/requirements.md)
- [`functional_decomposition.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/functional_decomposition.md)
- [`data_dictionary.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/data_dictionary.md)
- [`ui_spec.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/ui_spec.md)
- [`fmea.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/fmea.md)
- [`verification_validation.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/verification_validation.md)
- [`historical_validation.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/historical_validation.md)
- [`deployment.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/deployment.md)
- [`demo_assets.md`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/docs/demo_assets.md)

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

## Deployment

The repository includes:

- [`render.yaml`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/render.yaml)
- [`Procfile`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/Procfile)
- [`runtime.txt`](/c:/Users/Mihir/OneDrive/Desktop/doha_cascade/runtime.txt)

The current server entrypoint is:

```bash
gunicorn app:server
```

## Limitations

The project still has important limits:

- public real-data coverage is incomplete for full hub reconstruction
- historical downstream validation is not fully closed with trusted operational ground truth
- recovery optimization is discrete over candidate actions, not a network-wide mixed-integer optimizer
- the repository does not include a confirmed live public deployment URL
- the demo-assets folder is scaffolded but not yet populated with curated screenshots/video

These are real limitations and should be stated plainly.
