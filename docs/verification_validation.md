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

Run:

```bash
pytest -q
```

## Validation

Current validation level is prototype-grade:

- synthetic schedule behavior is internally consistent
- model assumptions are documented
- scenario outputs are plausible for demonstration and portfolio use

## Not Yet Complete

- formal comparison against 5-10 historical real-world disruptions
- pass/fail table against externally verified operational outcomes
- calibrated validation against airline-specific duty and connection data
