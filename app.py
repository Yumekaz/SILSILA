"""
app.py
------
SILSILA — Cytoscape network graph dashboard
Run:  python app.py
Open: http://localhost:8050
"""

import logging
import warnings
from datetime import datetime, timezone

import dash
import dash_cytoscape as cyto
import pandas as pd

from engine.config import USE_OPENSKY_BY_DEFAULT
from engine.data_loader import load_schedule
from engine.cyto_graph import build_cyto_stylesheet
from engine.graph_builder import build_graph, graph_summary
from ops.api import register_api
from ops.services import build_ops_platform
from ui.callbacks import register_callbacks, register_phase3_callbacks
from ui.layout import build_layout

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")

# Load Cytoscape extra layouts (cola, dagre, etc.) — optional but nice
cyto.load_extra_layouts()



def build_flight_options(df: pd.DataFrame, inbound_only: bool = True) -> list[dict]:
    """Build trigger options for the control panel."""
    flight_options = []
    source_df = df[df["direction"] == "inbound"] if inbound_only else df
    for _, row in source_df.sort_values("flight_id").iterrows():
        direction = "↓ IN" if row["direction"] == "inbound" else "↑ OUT"
        origin = row["origin"]
        dest = row["destination"]
        ref_time = row["arr_actual"] if row["direction"] == "inbound" else row["dep_scheduled"]
        time_str = ref_time.strftime("%H:%M") if pd.notna(ref_time) else "--:--"
        label = f"{row['flight_id']}  {direction}  {origin}→{dest}  {time_str}"
        flight_options.append({"label": label, "value": row["flight_id"]})
    return flight_options



def create_app(df: pd.DataFrame, graph, platform=None):
    """Initialise and wire the Dash application."""
    platform = platform or build_ops_platform(df, graph)
    flight_options = build_flight_options(df, inbound_only=True)

    app = dash.Dash(
        __name__,
        title="SILSILA · DOH",
        update_title=None,
        suppress_callback_exceptions=True,
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"}
        ],
    )
    initial_graph_elements = []
    initial_graph_stylesheet = build_cyto_stylesheet()
    app.layout = build_layout(
        flight_options,
        platform.data_quality.source_label,
        data_health_label=platform.data_quality.status,
        ops_mode_label=f"{platform.data_quality.mode} · {platform.settings.model_version}",
        initial_graph_elements=initial_graph_elements,
        initial_graph_stylesheet=initial_graph_stylesheet,
    )

    app.silsila_platform = platform
    app.server.config["silsila_platform"] = platform
    register_api(app.server, platform)

    register_callbacks(app, graph, df, platform=platform)
    register_phase3_callbacks(app, graph, df, platform=platform)
    return app



def load_runtime_context():
    """Load schedule and graph used by both local runs and deployment."""
    logger.info("Loading DOH schedule …")
    today = datetime.now(tz=timezone.utc)
    df = load_schedule(date=today, use_opensky=USE_OPENSKY_BY_DEFAULT)
    logger.info("Schedule: %d flights", len(df))

    logger.info("Building dependency graph …")
    graph = build_graph(df)
    summary = graph_summary(graph)
    logger.info(
        "Graph: %d nodes, %d edges  (%s)",
        summary["nodes"], summary["edges"],
        " | ".join(f"{k}:{v}" for k, v in summary["edge_types"].items()),
    )
    return df, graph



def build_runtime_app():
    """Create a fully-wired app using the current runtime schedule and graph."""
    df, graph = load_runtime_context()
    platform = build_ops_platform(df, graph)
    logger.info(
        "Data quality: %s / %s  ·  model %s",
        platform.data_quality.status,
        platform.data_quality.mode,
        platform.settings.model_version,
    )
    return create_app(df, graph, platform=platform)



def main():
    app = build_runtime_app()

    logger.info("─" * 60)
    logger.info("  SILSILA  ·  Cytoscape Ops Dashboard")
    logger.info("  http://localhost:8050")
    logger.info("─" * 60)

    app.run(
        debug=False,
        dev_tools_ui=False,
        dev_tools_hot_reload=False,
        host="0.0.0.0",
        port=8050,
    )


if __name__ == "__main__":
    main()
