# SILSILA
### Phase 1 — Graph Engine + Interactive Dashboard

**A systems engineering project** modelling how one flight delay at Hamad International Airport (DOH) 
propagates through Qatar Airways' hub network — with real flight data and a precision-grade ops UI.

---

## What This Is
One delayed inbound flight can cascade into 4–6 disrupted downstream flights, 
hundreds of stranded passengers, and tens of thousands of dollars in costs — in under 2 hours.
This simulator makes that cascade visible and quantifiable.

---

## Setup (5 minutes)

```bash
# 1. Clone / unzip the project
cd doha_cascade

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python app.py
```

Open **http://localhost:8050** in your browser.

---

## How to Use
1. **Select a trigger flight** from the dropdown (e.g. `QR007` — London inbound)
2. **Set the delay** using the slider (5 min → 4 hours)
3. **Click SIMULATE CASCADE**
4. Watch the network graph update, cascade log populate, and Gantt timeline shift

---

## Project Structure
```
doha_cascade/
├── app.py                  ← Entry point (run this)
├── requirements.txt
├── engine/
│   ├── data_loader.py      ← OpenSky API + synthetic DOH schedule
│   ├── graph_builder.py    ← NetworkX dependency graph
│   └── cascade.py          ← BFS cascade propagation algorithm
├── ui/
│   ├── layout.py           ← Dash layout components
│   └── callbacks.py        ← All reactive logic + figure builders
└── assets/
    └── style.css           ← Custom aviation ops UI (no templates)
```

---

## Phase Roadmap
| Phase | Status | Description |
|-------|--------|-------------|
| **1** | ✅ **Done** | Graph engine + cascade algorithm + Dash UI |
| 2     | Next   | Recovery heuristics (swap/delay/cancel) + cost comparison |
| 3     | Planned| Monte Carlo (500 scenarios) + risk heatmap + PDF export |

---

## Data Sources
- **OpenSky Network** — real Qatar Airways historical flight data (free API)
- **Synthetic fallback** — built from real QR routes, timing, and fleet data
- **No proprietary Qatar Airways data used**

---

## Tech Stack
`NetworkX` · `Plotly Dash` · `Pandas` · `NumPy` · `SciPy` · `Requests`
