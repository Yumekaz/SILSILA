# Data Dictionary

## Core Schedule Fields

- `flight_id`
  Unique flight identifier used as the node ID.
- `direction`
  `inbound` or `outbound`.
- `origin`
  Departure airport for inbound, hub for outbound.
- `destination`
  Hub for inbound, destination airport for outbound.
- `aircraft_reg`
  Tail registration used for rotation pairing.
- `aircraft_type`
  Human-readable aircraft family/type.
- `crew_id`
  Simplified crew assignment identifier.
- `seats`
  Seat capacity estimate.
- `load_factor`
  Fraction of seats occupied.
- `pax`
  Estimated passenger count.
- `arr_scheduled`
  Scheduled arrival timestamp.
- `arr_actual`
  Actual arrival timestamp.
- `dep_scheduled`
  Scheduled departure timestamp.
- `dep_actual`
  Actual departure timestamp.
- `arr_delay_min`
  Arrival delay in minutes.
- `dep_delay_min`
  Departure delay in minutes.
- `status`
  Flight state used by UI and report generation.
- `block_time_h`
  Approximate sector duration in hours.
- `turnaround_slack_min`
  Buffer above minimum turnaround.

## Graph Edge Fields

- `edge_type`
  `ROTATION`, `CREW`, or `PAX_CNXN`.
- `slack_min`
  Buffer before delay propagates.
- `vulnerability`
  Simplified 0-1 risk score for the dependency.
- `connecting_pax`
  Estimated transfer passengers on a connection edge.

## Cascade Summary Fields

- `flights_affected`
- `total_delay_min`
- `total_pax_affected`
- `total_pax_stranded`
- `estimated_cost_usd`
- `cascade_depth`
