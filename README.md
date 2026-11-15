# Emergency Diesel Decision-Support - GIS-driven prototype (v4)

Proof of concept for the PhD "Decision support for emergency fuel supply in New Zealand".
It shows the *structure* of the proposed tool using public OpenStreetMap data and **illustrative** parameters.

## Run
```
python -m pip install -r requirements.txt
python -m model.experiments        # 384 scenario runs -> results/
python -m model.make_figures       # static figures    -> results/figures/
python -m streamlit run dashboard/dashboard.py
```
`python model/gis_network.py` rebuilds the GIS dataset (internet needed); the generated `gis/` files are included.

## Structure
```
model/config.py       all assumptions (illustrative)
model/gis_data.py     GIS loading, segment-level hazards, route scoring
model/fuel_sim.py     the single simulation engine
model/experiments.py  severity x duration x 32 intervention packages, Pareto, recommendation
model/gis_network.py  OSM download / route builder
dashboard/dashboard.py
```

## What the model does
Terminal stock -> road distribution (real OSM routes) -> hospital + retail sites. A hazard closes a real road
segment; every route using it is blocked. An electricity outage raises hospital generator demand, halves terminal
loadout and stops pumps without backup power. Severity levels: L1 localised road damage (alternative exists),
L2 corridor closure (no road alternative to the hospital), L3 regional isolation (port exit closed + inbound supply cut).

Interventions: **A** demand prioritisation, **B** pre-positioning, **C** rerouting, **D** coastal shipping,
**E** NZDF/commercial alternative mode. KPIs: critical demand met/unmet, intervention cost, operational feasibility
(placeholder 1-5), general-demand side-effect. Recommendation = cheapest package that meets the service target at
acceptable feasibility.

## Changes from v3 (bugs fixed)
1. Disruption logic never matched real road segments (column-name mismatch), so only R01 was "closed". In fact the
   closed segment was on the port exit used by *all* routes, so the "rerouting restores 100 %" result was an artefact.
   Closure is now segment-level.
2. Route score had time and distance inverted (it preferred the slower/longer route). Fixed.
3. Three separate simulators with different logic were merged into one engine.
4. Added what the project describes but v3 lacked: finite upstream supply, electricity dependency, demand
   prioritisation, coastal shipping, NZDF/commercial support, cost and feasibility, severity x duration experiments,
   Pareto trade-offs.
5. Removed the pickle dependency (pandas-version fragile) and dead legacy files.

## Limitations (stated honestly)
One region, one terminal, one hospital; deterministic; no tanker-level logistics; no stochastic hazard; all numbers
illustrative; facilities are generic OSM geocodes, not real fuel assets. The PhD would add the national model,
validated data (MBIE/industry/NEMA/NZTA), uncertainty analysis and stakeholder-elicited feasibility.
The dashboard was written and syntax-checked but not executed in the build sandbox (no Streamlit available);
the simulation, experiments and figures were run and checked.
