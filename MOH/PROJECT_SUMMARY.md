# Project summary - emergency diesel decision-support prototype (v4)

**Purpose:** a small, runnable proof of concept of the methodology in the Waikato PhD project
"Decision support for emergency fuel supply in New Zealand" - not a model of the real NZ system.

| PhD project element | Prototype counterpart |
|---|---|
| National model: import terminal -> storage -> distribution -> retailers | Terminal (Port Nelson node) with finite stock/loadout/inbound supply -> road distribution -> retail sites |
| Demand profiles, inventories, storage and transport capacity | Hospital + 3 retail sites with a critical-fleet share; tank limits; fleet and route capacity |
| Dependencies (electricity) | Grid outage raises hospital generator demand, halves terminal loadout, stops pumps without backup power |
| Regional case study with GIS | Nelson-Tasman, OpenStreetMap network, segment-level road closure |
| Scenarios of varying severity and duration | 3 severities x 4 durations |
| Interventions: prioritisation, pre-positioning, coastal shipping, commercial/NZDF | A, B, D, E plus C rerouting; all 32 combinations |
| Metrics: met/unmet critical demand, cost, feasibility | All three reported, plus general-demand side-effect |
| Service-cost trade-offs | Pareto front + decision rule |
| Practical decision-support tool | Streamlit dashboard |

All numbers are illustrative (`model/config.py`) and would be replaced by validated data and stakeholder input.
