# Failure Modes And Effects Summary

## Key Failure Modes

| Failure Mode | Likely Cause | Effect | Current Mitigation | Status |
|---|---|---|---|---|
| Missing or unusable real schedule data | OpenSky unavailable or incomplete | Real-data path cannot support graph model | Synthetic fallback schedule | Implemented |
| No inbound triggers available | Bad schedule data | Simulation cannot run | Validation and exception path | Implemented |
| Recovery result drops residual impacts | Incomplete heuristic logic | False optimism in recovery output | Regression tests and corrected logic | Implemented |
| Export diverges from UI state | Recomputed payloads differ from viewed state | Misleading report | Store-based serialization | Partially mitigated |
| Monte Carlo takes too long | Large scenario count or slower host | Poor UX | Fixed default scenario count and lightweight charts | Partially mitigated |
| Model overstates realism | Simplified crew/pax assumptions | Incorrect interpretation by stakeholders | Explicit documentation of limitations | Implemented in docs |

## Recommended Next FMEA Iteration

- Add failure handling for cyclic or malformed graph data.
- Record data-source provenance in exported reports.
- Add explicit UI notices when synthetic fallback is active.
