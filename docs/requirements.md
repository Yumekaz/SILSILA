# Requirements

## Functional Requirements

`FR-1` The system shall load a Doha hub schedule from a supported data source.

`FR-2` The system shall represent flights and dependencies as a directed graph.

`FR-3` The user shall be able to select an inbound trigger flight and apply an initial delay.

`FR-4` The system shall propagate disruption through aircraft rotation, crew, and passenger connection dependencies.

`FR-5` The system shall display cascade outputs in an interactive dashboard.

`FR-6` The system shall evaluate three recovery heuristics: swap, compress/delay, and cancel.

`FR-7` The system shall run Monte Carlo scenarios for strategic risk analysis.

`FR-8` The system shall export a PDF report for the current scenario.

`FR-9` The system shall provide a turnaround sensitivity-analysis capability.

## Non-Functional Requirements

`NFR-1` The application shall run locally on a standard Python environment.

`NFR-2` The UI shall be usable without technical training.

`NFR-3` Monte Carlo analysis shall complete in practical interactive time for the default scenario count.

`NFR-4` The codebase shall be modular enough to separate data loading, graph logic, simulation, recovery, risk analysis, and UI.

`NFR-5` The project shall clearly document model assumptions and limitations.

## Status

- `FR-1` to `FR-8`: implemented
- `FR-9`: implemented
