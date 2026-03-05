# Historical Validation

This repo does not yet contain a full historical-validation package.

## Current State

- The code supports an OpenSky-based path.
- The default operational path remains the synthetic schedule because it is complete and reliable for graph construction.
- No 5-case or 10-case historical validation table is currently implemented.

## Partial Deliverable Included Here

Use the following template for future real-case validation:

| Case ID | Date | Trigger Flight | Observed Delay | Expected Downstream Impact | Model Output | Within Tolerance |
|---|---|---|---|---|---|---|
| HV-01 | TBD | TBD | TBD | TBD | TBD | TBD |
| HV-02 | TBD | TBD | TBD | TBD | TBD | TBD |
| HV-03 | TBD | TBD | TBD | TBD | TBD | TBD |
| HV-04 | TBD | TBD | TBD | TBD | TBD | TBD |
| HV-05 | TBD | TBD | TBD | TBD | TBD | TBD |

## Recommended Next Step

- Capture a small set of public historical disruptions.
- Reconstruct expected downstream events from public traces and schedules.
- Compare model totals for affected flights, delay minutes, and major event paths.
