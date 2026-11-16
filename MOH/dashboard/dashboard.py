"""Streamlit dashboard - Emergency diesel decision-support prototype (Nelson-Tasman, illustrative)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from model import config as C
from model import gis_data as G
from model.experiments import pareto_flag, recommend, run_combos
from model.fuel_sim import simulate

st.set_page_config(page_title="Emergency Fuel Decision-Support", page_icon="⛽", layout="wide")
st.markdown("<style>.block-container{padding-top:1.2rem}</style>", unsafe_allow_html=True)

NAMES = {k: v["name"] for k, v in C.INTERVENTIONS.items()}


@st.cache_data(show_spinner=False)
def combos_for(sev: str, dur: float) -> pd.DataFrame:
    df = run_combos(sev, dur)
    df["pareto"] = pareto_flag(df)
    return df


@st.cache_data(show_spinner=False)
def series_for(sev: str, dur: float, combo: str) -> pd.DataFrame:
    ints = frozenset() if combo == "None" else frozenset(combo.split("+"))
    return simulate(sev, dur, ints, record=True)[1]


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Hazard scenario")
    sev = st.selectbox("Severity", list(C.SEVERITIES), format_func=lambda k: C.SEVERITIES[k]["label"])
    dur = st.select_slider("Road-closure duration (h)", options=C.DURATIONS_H, value=48)
    st.header("Decision rule")
    target = st.slider("Target critical service (%)", 80, 100, int(C.TARGET_CRITICAL_SERVICE_PCT))
    min_feas = st.slider("Minimum operational feasibility (1-5)", 1, 5, C.MIN_FEASIBILITY)
    st.header("Compare a specific package")
    chosen = st.multiselect("Interventions", list(NAMES), format_func=lambda k: f"{k} - {NAMES[k]}")
    st.caption("All parameters are illustrative (model/config.py). Not for operational use.")

df = combos_for(sev, float(dur))
best, met = recommend(df, target, min_feas)
base = df[df.interventions == "None"].iloc[0]
chosen_label = "+".join(sorted(chosen)) if chosen else "None"
sel = df[df.interventions == chosen_label].iloc[0]

st.title("Emergency Diesel Decision-Support")
st.caption(
    "Nelson-Tasman proof of concept | OpenStreetMap road network | "
    "terminal -> road distribution -> critical + retail sites | electricity dependency | 5 interventions"
)

# ------------------------------------------------------------------ headline
c1, c2, c3 = st.columns([1.1, 1.4, 1.1], gap="large")
with c1:
    st.subheader("Recommendation")
    (st.success if met else st.warning)(
        f"{'Target met' if met else 'Target NOT reachable at this feasibility'}: "
        f"**{best.interventions}**"
    )
    if best.interventions != "None":
        for k in best.interventions.split("+"):
            st.markdown(f"- **{k}** {NAMES[k]}")
    st.metric("Critical demand met", f"{best.critical_met_pct:.1f}%", f"{best.critical_met_pct - base.critical_met_pct:+.1f} pts vs no action")
    st.metric("Intervention cost", f"NZ$ {best.intervention_cost_nzd:,.0f}")
    st.metric("General demand met (side-effect)", f"{best.general_met_pct:.1f}%")
    st.metric("Operational feasibility", f"{int(best.feasibility)} / 5")

with c2:
    st.subheader("GIS map: hazard and routes")
    fig = go.Figure()
    blocked = G.hazard_blocked_routes(C.SEVERITIES[sev]["road_hazard"])
    for _, r in G.od_routes(C.TERMINAL_ID, C.HOSPITAL_ID).iterrows():
        poly = G.route_polyline(r.route_id)
        is_b = r.route_id in blocked
        fig.add_trace(go.Scattermap(
            lon=[p[0] for p in poly], lat=[p[1] for p in poly], mode="lines",
            line=dict(width=6 if is_b else 4, color="#d62728" if is_b else "#16803c"),
            name=f"{r.route_id} {'blocked' if is_b else 'open'}"))
    hz = G.hazard_polyline(C.SEVERITIES[sev]["road_hazard"])
    fig.add_trace(go.Scattermap(lon=[p[0] for p in hz], lat=[p[1] for p in hz], mode="lines",
                                line=dict(width=12, color="#000000"), name="Closed segment (approx.)"))
    fac = G.load_facilities()
    fig.add_trace(go.Scattermap(lon=fac.longitude, lat=fac.latitude, mode="markers+text", text=fac.name,
                                textposition="top right", marker=dict(size=11, color="#1769aa"), name="Facilities"))
    fig.update_layout(map=dict(style="open-street-map",
                               center=dict(lat=float(fac.latitude.mean()), lon=float(fac.longitude.mean())), zoom=11.2),
                      height=470, margin=dict(l=0, r=0, t=0, b=0),
                      legend=dict(orientation="h", y=0.01, bgcolor="rgba(255,255,255,.85)"))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Routes blocked to the hospital by this hazard: "
               f"{', '.join(sorted(blocked & set(G.od_routes(C.TERMINAL_ID, C.HOSPITAL_ID).route_id))) or 'none'} "
               f"(segment-level check on shared OSM road segments).")

with c3:
    st.subheader("Selected package")
    st.markdown(f"**{chosen_label}**")
    st.metric("Critical demand met", f"{sel.critical_met_pct:.1f}%")
    st.metric("Hospital shortage", f"{sel.hospital_shortage_h:.2f} h")
    st.metric("Cost", f"NZ$ {sel.intervention_cost_nzd:,.0f}")
    st.metric("Feasibility", f"{int(sel.feasibility)} / 5")

# ------------------------------------------------------------------ trade-off
st.divider()
a, b = st.columns(2, gap="large")
with a:
    st.subheader("Service-cost trade-off (all 32 packages)")
    d = df.copy()
    d["cost_k"] = d.intervention_cost_nzd / 1000
    f2 = go.Figure()
    for flag, col, nm in [(False, "#9ca3af", "Dominated"), (True, "#1769aa", "Pareto-efficient")]:
        s = d[d.pareto == flag]
        f2.add_trace(go.Scatter(x=s.cost_k, y=s.critical_met_pct, mode="markers+text" if flag else "markers",
                                text=s.interventions if flag else None, textposition="top center",
                                marker=dict(size=10, color=col), name=nm))
    f2.add_hline(y=target, line_dash="dash", annotation_text="Target")
    f2.update_layout(xaxis_title="Intervention cost (NZ$ thousand)", yaxis_title="Critical demand met (%)",
                     height=400, margin=dict(l=10, r=10, t=20, b=40))
    st.plotly_chart(f2, use_container_width=True)
with b:
    st.subheader("Hospital and terminal stock over time")
    ts = series_for(sev, float(dur), chosen_label)
    ts0 = series_for(sev, float(dur), "None")
    f3 = go.Figure()
    f3.add_trace(go.Scatter(x=ts0.time_h, y=ts0.hospital_L, name="Hospital - no action", line=dict(color="#d62728", dash="dot")))
    f3.add_trace(go.Scatter(x=ts.time_h, y=ts.hospital_L, name=f"Hospital - {chosen_label}", line=dict(color="#1769aa", width=3)))
    f3.add_trace(go.Scatter(x=ts.time_h, y=ts.terminal_L / 10, name=f"Terminal (/10) - {chosen_label}", line=dict(color="#6b7280")))
    f3.add_vrect(x0=C.EVENT_START_H, x1=C.EVENT_START_H + dur, fillcolor="#d62728", opacity=0.08, line_width=0,
                 annotation_text="Road closed")
    f3.update_layout(xaxis_title="Time (h)", yaxis_title="Litres", height=400, margin=dict(l=10, r=10, t=20, b=40),
                     hovermode="x unified")
    st.plotly_chart(f3, use_container_width=True)

st.subheader("All intervention packages")
show = df.sort_values(["critical_met_pct", "intervention_cost_nzd"], ascending=[False, True])[
    ["interventions", "critical_met_pct", "hospital_shortage_h", "general_met_pct",
     "intervention_cost_nzd", "feasibility", "pareto"]].rename(columns={
        "interventions": "Package", "critical_met_pct": "Critical met (%)", "hospital_shortage_h": "Hospital shortage (h)",
        "general_met_pct": "General met (%)", "intervention_cost_nzd": "Cost (NZ$)", "feasibility": "Feasibility",
        "pareto": "Pareto"})
st.dataframe(show.round(1), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ severity x duration map
st.divider()
st.subheader("Recommended package across severity and duration")
rec_path = ROOT / "results" / "recommendations.csv"
if rec_path.exists():
    rec = pd.read_csv(rec_path)
    pivot = rec.pivot(index="severity", columns="duration_h", values="recommended")
    st.dataframe(pivot, use_container_width=True)
    st.caption("Precomputed with the default decision rule (python -m model.experiments).")

with st.expander("Model structure and assumptions"):
    st.markdown("""
**Supply chain:** terminal/bulk storage (Port Nelson node) -> road distribution on the OpenStreetMap network -> hospital + 3 retail sites (each with a critical-fleet share).
**Hazards:** a real OSM road segment is closed; every route using it is blocked (segment-level, so route diversity is genuine).
**Dependencies:** electricity outage raises hospital diesel demand (generators), halves terminal loadout and stops pumps at stations without backup power; severe case also cuts inbound supply.
**Interventions:** A prioritisation, B pre-positioning, C rerouting, D coastal shipping, E NZDF/commercial alternative mode.
**KPIs:** met/unmet critical demand, intervention cost, operational feasibility (placeholder 1-5 scores), general-demand side-effect.
**Limits:** one region, one terminal, one hospital, deterministic, illustrative numbers. The PhD would add the national model, real data, stochastic hazards, stakeholder-validated feasibility.
""")
