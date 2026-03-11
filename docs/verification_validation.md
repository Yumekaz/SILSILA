# Verification And Validation

## Verification

Current automated checks cover:

- schedule schema validity
- schedule and graph validation reports
- graph edge construction sanity
- rotation slack correctness
- cascade propagation updates for inbound and outbound triggers
- recovery regression scenarios
- optimizer selection behavior
- Monte Carlo output structure
- PDF generation smoke path
- state serialization round trips
- turnaround sensitivity-analysis output
- Pareto-front recovery annotation output
- historical validation suite regression coverage

Run:

```bash
pytest -q
```

## Validation

Current validation level is now stronger than prototype-only:

- synthetic schedule behavior is internally consistent
- model assumptions are documented
- cost calibration is tied to published references
- scenario outputs are benchmarked against five public disruption references using analog mapping and tolerance bands

## External-Case Benchmarking

The historical validation harness lives in `engine/historical_validation.py` and is documented in `docs/historical_validation.md`.

What it checks:

- moderate long-haul inbound delay realism
- severe long-haul heavy-tail propagation
- low-delay baseline behavior
- rotation-led widebody spillover
- crew-driven deep cascade behavior

## Still Not Complete

- airline-internal downstream truth data for exact connection misses, duty illegality, and swap decisions
- one-to-one replay validation against OCC logs or airport operations datasets
- calibrated validation against airline-specific duty and connection data
