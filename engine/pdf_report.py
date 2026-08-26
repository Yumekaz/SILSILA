"""
pdf_report.py
-------------
Phase 3: Auto-generate a professional PDF report from a SILSILA session.

Sections:
  1. Cover — SILSILA branding, session metadata
  2. Cascade Summary — trigger, affected flights, cost breakdown
  3. Recovery Comparison — side-by-side SWAP / DELAY / CANCEL table
  4. Monte Carlo Results — network risk distribution stats
  5. Risk Heatmap — per-flight risk scores table
  6. Systems Engineering Note — integration architecture sketch

Uses ReportLab (pure Python, no browser dependency).
"""

from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak,
)

# ── Brand colours ──────────────────────────────────────────────────────────────
C_NAVY   = colors.HexColor("#0C1220")
C_BLUE   = colors.HexColor("#172039")
C_GOLD   = colors.HexColor("#E8A020")
C_CYAN   = colors.HexColor("#00C8FF")
C_TEAL   = colors.HexColor("#75E0C0")
C_RED    = colors.HexColor("#FF3D5A")
C_ORANGE = colors.HexColor("#FF6B35")
C_TEXT   = colors.HexColor("#1A2A40")
C_MUTED  = colors.HexColor("#82768A")
C_LIGHT  = colors.HexColor("#EAF2FB")
C_WHITE  = colors.white
C_BLACK  = colors.black

W, H = A4   # 210 x 297 mm


# ── Styles ──────────────────────────────────────────────────────────────────────
def _build_styles():
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle("cover_title",
            fontName="Helvetica-Bold", fontSize=34, textColor=C_WHITE,
            leading=40, alignment=TA_CENTER, spaceAfter=6),
        "cover_sub": ParagraphStyle("cover_sub",
            fontName="Helvetica", fontSize=13, textColor=C_GOLD,
            leading=18, alignment=TA_CENTER, spaceAfter=4),
        "cover_meta": ParagraphStyle("cover_meta",
            fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#C3B9C7"),
            leading=14, alignment=TA_CENTER),
        "section_title": ParagraphStyle("section_title",
            fontName="Helvetica-Bold", fontSize=14, textColor=C_NAVY,
            leading=18, spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("body",
            fontName="Helvetica", fontSize=9, textColor=C_TEXT,
            leading=14, spaceAfter=4),
        "body_bold": ParagraphStyle("body_bold",
            fontName="Helvetica-Bold", fontSize=9, textColor=C_TEXT,
            leading=14, spaceAfter=4),
        "label": ParagraphStyle("label",
            fontName="Helvetica", fontSize=8, textColor=C_MUTED,
            leading=12, spaceAfter=2),
        "big_number": ParagraphStyle("big_number",
            fontName="Helvetica-Bold", fontSize=22, textColor=C_GOLD,
            leading=26, alignment=TA_CENTER),
        "footnote": ParagraphStyle("footnote",
            fontName="Helvetica", fontSize=7, textColor=C_MUTED,
            leading=10, spaceAfter=2),
    }


# ── Table helpers ───────────────────────────────────────────────────────────────
def _header_row_style(n_cols: int) -> list:
    return [
        ("BACKGROUND",   (0, 0), (n_cols-1, 0), C_NAVY),
        ("TEXTCOLOR",    (0, 0), (n_cols-1, 0), C_WHITE),
        ("FONTNAME",     (0, 0), (n_cols-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (n_cols-1, 0), 8),
        ("BOTTOMPADDING",(0, 0), (n_cols-1, 0), 6),
        ("TOPPADDING",   (0, 0), (n_cols-1, 0), 6),
    ]


def _data_row_styles(n_rows: int, n_cols: int) -> list:
    styles = []
    for i in range(1, n_rows):
        bg = C_LIGHT if i % 2 == 0 else C_WHITE
        styles.append(("BACKGROUND", (0, i), (n_cols-1, i), bg))
    styles += [
        ("FONTNAME",     (0, 1), (n_cols-1, n_rows-1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (n_cols-1, n_rows-1), 8),
        ("TOPPADDING",   (0, 1), (n_cols-1, n_rows-1), 4),
        ("BOTTOMPADDING",(0, 1), (n_cols-1, n_rows-1), 4),
        ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#CCDDEE")),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_LIGHT]),
    ]
    return styles


# ── Cover page ─────────────────────────────────────────────────────────────────
def _cover_section(story, styles, session_meta: dict):
    # Dark background block using a table
    cover_data = [[
        Paragraph("SILSILA", styles["cover_title"]),
    ], [
        Paragraph("Doha Hub Disruption Cascade Simulator", styles["cover_sub"]),
    ], [
        Paragraph("Phase 3 Analysis Report", styles["cover_meta"]),
    ], [
        Paragraph(f"Generated: {session_meta.get('timestamp', '—')}", styles["cover_meta"]),
    ], [
        Paragraph("Hamad International Airport · DOH/OTHH · Qatar Airways Hub", styles["cover_meta"]),
    ]]

    t = Table(cover_data, colWidths=[170*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("TOPPADDING",    (0, 0), (-1, 0), 28),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 28),
        ("LEFTPADDING",   (0, 0), (-1, -1), 20),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 20),
    ]))
    story.append(t)
    story.append(Spacer(1, 8*mm))

    # Metadata row
    meta_data = [[
        Paragraph("TRIGGER", styles["label"]),
        Paragraph("DELAY", styles["label"]),
        Paragraph("FLIGHTS HIT", styles["label"]),
        Paragraph("TOTAL COST", styles["label"]),
        Paragraph("SCENARIOS", styles["label"]),
    ], [
        Paragraph(session_meta.get("trigger", "—"), styles["body_bold"]),
        Paragraph(f"+{session_meta.get('delay_min', 0):.0f} min", styles["body_bold"]),
        Paragraph(str(session_meta.get("flights_affected", 0)), styles["body_bold"]),
        Paragraph(f"${session_meta.get('baseline_cost', 0):,.0f}", styles["body_bold"]),
        Paragraph(str(session_meta.get("n_scenarios", 0)), styles["body_bold"]),
    ]]
    mt = Table(meta_data, colWidths=[34*mm]*5)
    mt.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_MUTED),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, 0), 7),
        ("BACKGROUND",    (0, 1), (-1, 1), C_LIGHT),
        ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 1), (-1, 1), 10),
        ("TEXTCOLOR",     (0, 1), (-1, 1), C_NAVY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#CCDDEE")),
    ]))
    story.append(mt)


# ── Cascade section ─────────────────────────────────────────────────────────────
def _cascade_section(story, styles, cascade_summary: dict):
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=C_GOLD, spaceAfter=4))
    story.append(Paragraph("01 — CASCADE ANALYSIS", styles["section_title"]))
    story.append(Paragraph(
        f"Flight <b>{cascade_summary.get('trigger','—')}</b> arrived "
        f"<b>+{cascade_summary.get('trigger_delay_min',0):.0f} minutes late</b>, "
        f"triggering a cascade that affected <b>{cascade_summary.get('flights_affected',0)} "
        f"downstream flights</b> across {cascade_summary.get('cascade_depth',0)} propagation "
        f"layer(s). Total accumulated delay: <b>{cascade_summary.get('total_delay_min',0):.0f} minutes</b>. "
        f"Estimated network cost: <b>${cascade_summary.get('estimated_cost_usd',0):,.0f}</b>.",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    data = [["Flight", "Direction", "Edge Type", "Delay (min)", "PAX Affected", "Est. Cost (USD)"]]
    events = cascade_summary.get("events", [])
    for e in events:
        sev_color = C_RED if e.get("severity") == "CRITICAL" else (
            C_ORANGE if e.get("severity") == "HIGH" else C_TEXT
        )
        data.append([
            e.get("flight_id", "—"),
            e.get("direction", "—").upper(),
            e.get("edge_type", "—"),
            f"+{e.get('delay_min', 0):.0f}",
            f"{e.get('pax_affected', 0):,}",
            f"${e.get('cost_usd', 0):,.0f}",
        ])

    if len(data) > 1:
        t = Table(data, colWidths=[28*mm, 28*mm, 28*mm, 28*mm, 30*mm, 28*mm])
        t.setStyle(TableStyle(
            _header_row_style(6) + _data_row_styles(len(data), 6)
        ))
        story.append(t)
    else:
        story.append(Paragraph("No cascade events — delay was absorbed within existing turnaround slack.", styles["body"]))


# ── Recovery section ───────────────────────────────────────────────────────────
def _recovery_section(story, styles, recovery_options: list):
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=C_CYAN, spaceAfter=4))
    story.append(Paragraph("02 — RECOVERY OPTIONS COMPARISON", styles["section_title"]))
    story.append(Paragraph(
        "Three recovery heuristics evaluated against the no-action baseline. "
        "Score (0–100) weights delay reduction (55%) and cost efficiency (45%). "
        "Higher score = better overall option for this disruption scenario.",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    data = [["Strategy", "Feasible", "Delay Cut", "Direct Cost", "Net Cost", "PAX Saved", "Score"]]
    for opt in recovery_options:
        data.append([
            opt.get("label", "—"),
            "YES" if opt.get("feasible") else "NO",
            f"{opt.get('delay_reduction_min', 0):.0f}m ({opt.get('delay_reduction_pct', 0):.0f}%)",
            f"${opt.get('direct_cost_usd', 0):,.0f}",
            f"${opt.get('net_cost_usd', 0):,.0f}",
            str(opt.get("pax_saved", 0)),
            f"{opt.get('score', 0):.1f}",
        ])

    t = Table(data, colWidths=[32*mm, 20*mm, 30*mm, 28*mm, 26*mm, 22*mm, 12*mm])
    t.setStyle(TableStyle(
        _header_row_style(7) + _data_row_styles(len(data), 7)
    ))
    story.append(t)


# ── Monte Carlo section ────────────────────────────────────────────────────────
def _monte_carlo_section(story, styles, mc_summary: dict):
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=C_TEAL, spaceAfter=4))
    story.append(Paragraph("03 — MONTE CARLO RISK ANALYSIS", styles["section_title"]))

    n = mc_summary.get("n_scenarios", 0)
    zero_pct = mc_summary.get("zero_cascade_pct", 0)
    crit_pct = mc_summary.get("critical_scenario_pct", 0)

    story.append(Paragraph(
        f"<b>{n} disruption scenarios</b> simulated using delay magnitudes sampled from a "
        f"lognormal distribution calibrated to EUROCONTROL 2024 data "
        f"(μ_log = 2.85, σ_log = 0.95 → median initial delay ≈ 17 min, matching the "
        f"17.5 min/flight network average). "
        f"<b>{zero_pct:.1f}%</b> of scenarios produced no cascade (delay absorbed within slack). "
        f"<b>{crit_pct:.1f}%</b> of scenarios exceeded the critical cost threshold "
        f"(>${mc_summary.get('critical_cost_threshold', 50000):,.0f}).",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    # Stats table
    stats_data = [
        ["Metric", "Mean", "P50 (Median)", "P90", "P99"],
        [
            "Flights Affected per Scenario",
            f"{mc_summary.get('mean_flights_affected', 0):.2f}",
            f"{mc_summary.get('p50_flights_affected', 0):.1f}",
            f"{mc_summary.get('p90_flights_affected', 0):.1f}",
            f"{mc_summary.get('p99_flights_affected', 0):.1f}",
        ],
        [
            "Cascade Cost per Scenario (USD)",
            f"${mc_summary.get('mean_cost_usd', 0):,.0f}",
            f"${mc_summary.get('p50_cost_usd', 0):,.0f}",
            f"${mc_summary.get('p90_cost_usd', 0):,.0f}",
            f"${mc_summary.get('p99_cost_usd', 0):,.0f}",
        ],
        [
            "Total Cascade Delay per Scenario (min)",
            f"{mc_summary.get('mean_total_delay', 0):.1f}",
            "—",
            f"{mc_summary.get('p90_total_delay', 0):.1f}",
            "—",
        ],
    ]
    t = Table(stats_data, colWidths=[68*mm, 26*mm, 26*mm, 26*mm, 24*mm])
    t.setStyle(TableStyle(
        _header_row_style(5) + _data_row_styles(len(stats_data), 5)
    ))
    story.append(t)
    story.append(Spacer(1, 4*mm))

    # Top triggers
    top = mc_summary.get("top_triggers", [])
    if top:
        story.append(Paragraph("<b>Top 5 Highest-Risk Trigger Flights:</b>", styles["body_bold"]))
        trig_data = [["Flight", "Avg Cascade Cost When Triggered"]]
        for fid, cost in top:
            trig_data.append([fid, f"${cost:,.0f}"])
        tt = Table(trig_data, colWidths=[60*mm, 110*mm])
        tt.setStyle(TableStyle(
            _header_row_style(2) + _data_row_styles(len(trig_data), 2)
        ))
        story.append(tt)


# ── Risk heatmap section ───────────────────────────────────────────────────────
def _risk_heatmap_section(story, styles, risk_profiles: dict):
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=C_ORANGE, spaceAfter=4))
    story.append(Paragraph("04 — PER-FLIGHT RISK PROFILES", styles["section_title"]))
    story.append(Paragraph(
        "Risk score combines trigger risk (how severe are cascades caused by this flight) "
        "and victim probability (how often this flight is hit by cascades from others). "
        "Both components weighted 50/50.",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    data = [["Flight", "Direction", "Route", "Aircraft", "Trigger Avg Cost", "Victim P(%)", "Risk Score", "Label"]]
    for fid, p in sorted(risk_profiles.items(), key=lambda x: x[1].risk_score, reverse=True):
        label_color = (
            C_RED if p.risk_label == "CRITICAL" else
            C_ORANGE if p.risk_label == "HIGH" else
            C_GOLD if p.risk_label == "MEDIUM" else C_TEAL
        )
        data.append([
            fid,
            p.direction.upper(),
            f"{p.origin}→{p.destination}",
            p.aircraft_type,
            f"${p.trigger_avg_cost:,.0f}",
            f"{p.victim_probability*100:.1f}%",
            f"{p.risk_score:.3f}",
            p.risk_label,
        ])

    t = Table(data, colWidths=[18*mm, 18*mm, 24*mm, 24*mm, 28*mm, 22*mm, 20*mm, 16*mm])
    t.setStyle(TableStyle(
        _header_row_style(8) + _data_row_styles(len(data), 8)
    ))
    story.append(t)


# ── SE integration note ────────────────────────────────────────────────────────
def _se_note_section(story, styles):
    story.append(PageBreak())
    story.append(HRFlowable(width="100%", thickness=2, color=C_GOLD, spaceAfter=4))
    story.append(Paragraph("05 — SYSTEMS ENGINEERING NOTE", styles["section_title"]))
    story.append(Paragraph(
        "How SILSILA could integrate with Qatar Airways AI Skyways (Accenture, 2025)",
        styles["body_bold"]
    ))
    story.append(Spacer(1, 3*mm))

    note_data = [
        ["SE Layer", "SILSILA Component", "AI Skyways Integration Point"],
        ["Data Ingestion", "OpenSky Network API → schedule DataFrame",
         "Replace with real-time ACARS/ADS-B feed from QR ops system"],
        ["Network Model", "NetworkX DiGraph (ROTATION, CREW, PAX_CNXN edges)",
         "Extend with full crew pairing data and slot constraints from BEONTRA"],
        ["Cascade Engine", "BFS propagation with edge-type rules",
         "Plug in as predictive layer: 'X flight is 30 min late → here is predicted cascade'"],
        ["Recovery Heuristics", "SWAP / DELAY / CANCEL with cost scoring",
         "Feed into AI Skyways recommendation engine as candidate actions"],
        ["Monte Carlo", "500 lognormal-sampled scenarios → risk profiles",
         "Run nightly on tomorrow's schedule → pre-position spares at high-risk rotations"],
        ["Output", "Interactive Dash dashboard + PDF report",
         "Embed heatmap view in existing QR operations briefing tools"],
    ]

    t = Table(note_data, colWidths=[38*mm, 62*mm, 70*mm])
    t.setStyle(TableStyle(
        _header_row_style(3) + _data_row_styles(len(note_data), 3) + [
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("LEADING",  (0, 1), (-1, -1), 11),
        ]
    ))
    story.append(t)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Data sources: OpenSky Network (public), Qatar Airways public timetable, "
        "EUROCONTROL Standard Inputs Ed. 10, ECB exchange-rate references, EUR-Lex 261/2004, and UK CAA passenger-rights guidance. "
        "No proprietary Qatar Airways operational data used.",
        styles["footnote"]
    ))


# ── Master builder ─────────────────────────────────────────────────────────────
def generate_pdf_report(
    cascade_summary: dict,
    recovery_options: list,
    mc_result,
    output_path: str,
) -> str:
    """
    Generate the full SILSILA PDF report.

    Parameters
    ----------
    cascade_summary   : dict from CascadeResult.summary() + events list
    recovery_options  : list of RecoveryOption dicts
    mc_result         : MonteCarloResult object
    output_path       : where to write the PDF

    Returns output_path.
    """
    styles = _build_styles()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title="SILSILA — Doha Hub Disruption Report",
        author="SILSILA Phase 3",
    )

    story = []

    # ── Cover ──────────────────────────────────────────────────────────────────
    session_meta = {
        "timestamp":       datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "trigger":         cascade_summary.get("trigger", "—"),
        "delay_min":       cascade_summary.get("trigger_delay_min", 0),
        "flights_affected":cascade_summary.get("flights_affected", 0),
        "baseline_cost":   cascade_summary.get("estimated_cost_usd", 0),
        "n_scenarios":     mc_result.n_scenarios if mc_result else 0,
    }
    _cover_section(story, styles, session_meta)

    # ── Cascade ────────────────────────────────────────────────────────────────
    _cascade_section(story, styles, cascade_summary)

    # ── Recovery ───────────────────────────────────────────────────────────────
    if recovery_options:
        _recovery_section(story, styles, recovery_options)

    # ── Monte Carlo ────────────────────────────────────────────────────────────
    if mc_result and mc_result.network_summary:
        ns = mc_result.network_summary
        mc_dict = {
            "n_scenarios":           ns.n_scenarios,
            "mean_flights_affected": ns.mean_flights_affected,
            "p50_flights_affected":  ns.p50_flights_affected,
            "p90_flights_affected":  ns.p90_flights_affected,
            "p99_flights_affected":  ns.p99_flights_affected,
            "mean_cost_usd":         ns.mean_cost_usd,
            "p50_cost_usd":          ns.p50_cost_usd,
            "p90_cost_usd":          ns.p90_cost_usd,
            "p99_cost_usd":          ns.p99_cost_usd,
            "mean_total_delay":      ns.mean_total_delay,
            "p90_total_delay":       ns.p90_total_delay,
            "zero_cascade_pct":      ns.zero_cascade_pct,
            "critical_scenario_pct": ns.critical_scenario_pct,
            "critical_cost_threshold": 50_000,
            "top_triggers":          ns.top_triggers,
        }
        _monte_carlo_section(story, styles, mc_dict)

        # Risk profiles
        _risk_heatmap_section(story, styles, mc_result.risk_profiles)

    # ── SE Note ────────────────────────────────────────────────────────────────
    _se_note_section(story, styles)

    doc.build(story)
    return output_path

