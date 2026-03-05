# UI Specification

## Main Views

- Header
  Branding, system status, and live clock.
- Control panel
  Trigger-flight selector, delay slider, run/reset actions, scenario metrics.
- Network panel
  Cytoscape graph with dependency edges.
- Cascade log
  Ordered impact list with severity and propagation path.
- Recovery panel
  Three strategy cards with score, cost, and action log.
- Gantt timeline
  Original vs impacted schedule view.
- Monte Carlo panel
  Distribution charts, heatmap, and export action.

## Interaction Rules

- Trigger selection is restricted to inbound flights.
- Recovery actions become meaningful only after a cascade run.
- Monte Carlo analysis is triggered on demand.
- PDF export consumes persisted callback state where available.

## Responsiveness

- The app is usable on desktop and small laptop widths.
- Mobile support is basic and functional, but not yet supported by a formal screenshot/demo set.
