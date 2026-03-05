"""
app.py
------
Doha Hub Disruption Cascade Simulator — Phase 1
Run:  python app.py
Open: http://localhost:8050
"""

import logging
import warnings
from datetime import datetime, timezone

import dash
import pandas as pd

from engine.data_loader   import load_schedule
from engine.graph_builder import build_graph, graph_summary
from ui.layout            import build_layout
from ui.callbacks         import register_callbacks

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")


def main():
    # ── Load schedule ──────────────────────────────────────────────────────────
    logger.info("Loading DOH schedule …")
    today = datetime.now(tz=timezone.utc)
    df    = load_schedule(date=today, use_opensky=True)
    logger.info("Schedule: %d flights", len(df))

    # ── Build dependency graph ─────────────────────────────────────────────────
    logger.info("Building dependency graph …")
    G = build_graph(df)
    summary = graph_summary(G)
    logger.info(
        "Graph: %d nodes, %d edges  (%s)",
        summary["nodes"], summary["edges"],
        " | ".join(f"{k}:{v}" for k, v in summary["edge_types"].items())
    )

    # ── Build flight selector options ──────────────────────────────────────────
    flight_options = []
    for _, row in df.sort_values("flight_id").iterrows():
        direction = "↓ IN" if row["direction"] == "inbound" else "↑ OUT"
        origin    = row["origin"]
        dest      = row["destination"]
        ref_time  = (row["arr_actual"] if row["direction"] == "inbound"
                     else row["dep_scheduled"])
        time_str  = ref_time.strftime("%H:%M") if pd.notna(ref_time) else "--:--"
        label     = f"{row['flight_id']}  {direction}  {origin}→{dest}  {time_str}"
        flight_options.append({"label": label, "value": row["flight_id"]})

    # ── Initialise Dash ────────────────────────────────────────────────────────
    app = dash.Dash(
        __name__,
        title="QR Cascade Sim · DOH",
        update_title=None,
        suppress_callback_exceptions=True,
        meta_tags=[
            {"name": "viewport",
             "content": "width=device-width, initial-scale=1"}
        ],
    )
    app.layout = build_layout(flight_options)

    # Register all callbacks (pass G and df into closure)
    register_callbacks(app, G, df)

    logger.info("─" * 60)
    logger.info("  DOHA CASCADE SIMULATOR  ·  Phase 1")
    logger.info("  http://localhost:8050")
    logger.info("─" * 60)

    app.run(debug=True, host="0.0.0.0", port=8050)


if __name__ == "__main__":
    main()
