# Functional Decomposition

## Top-Level Flow

1. Data ingestion
2. Schedule normalization
3. Dependency graph construction
4. Cascade propagation
5. Recovery evaluation
6. Risk simulation
7. Visualization and reporting

## Module Mapping

- `engine/data_loader.py`
  Loads or synthesizes schedule data.
- `engine/graph_builder.py`
  Builds dependency graph edges for rotation, crew, and passenger connections.
- `engine/cascade.py`
  Runs propagation logic and produces scenario summaries.
- `engine/recovery.py`
  Evaluates heuristic recovery options.
- `engine/monte_carlo.py`
  Runs repeated disruption scenarios and aggregates risk metrics.
- `engine/sensitivity.py`
  Sweeps turnaround assumptions to study model sensitivity.
- `engine/pdf_report.py`
  Produces a presentation-friendly report.
- `ui/layout.py`
  Defines layout and stores.
- `ui/callbacks_core.py`
  Handles simulation and recovery interactions.
- `ui/callbacks_phase3.py`
  Handles Monte Carlo analysis and export.
- `ui/session_state.py`
  Serializes state between callbacks and report generation.
