"""Static figures for the application pack: python -m model.make_figures"""
from __future__ import annotations
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from . import config as C, gis_data as G
from .experiments import run_all
from .fuel_sim import simulate

OUT = Path(__file__).resolve().parents[1] / "results" / "figures"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    grid, recs = run_all()

    # 1. Pareto for L2 / 48 h
    d = grid[(grid.severity == "L2") & (grid.duration_h == 48)]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(d.intervention_cost_nzd / 1e3, d.critical_met_pct, c=["#1769aa" if p else "#b0b5bb" for p in d.pareto], s=40)
    for _, r in d[d.pareto].iterrows():
        ax.annotate(r.interventions, (r.intervention_cost_nzd / 1e3, r.critical_met_pct), xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.axhline(C.TARGET_CRITICAL_SERVICE_PCT, ls="--", c="k", lw=1)
    ax.set_xlabel("Intervention cost (NZ$ thousand)"); ax.set_ylabel("Critical demand met (%)")
    ax.set_title("L2 corridor closure, 48 h: service vs cost (blue = Pareto-efficient)")
    fig.tight_layout(); fig.savefig(OUT / "pareto_L2_48h.png", dpi=160); plt.close(fig)

    # 2. Stock time series
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for combo, col in [("None", "#d62728"), ("A", "#f59e0b"), ("B", "#6b7280"), ("A+B", "#1769aa")]:
        ints = frozenset() if combo == "None" else frozenset(combo.split("+"))
        ts = simulate("L2", 48, ints)[1]
        ax.plot(ts.time_h, ts.hospital_L, label=combo, c=col, lw=2)
    ax.axvspan(C.EVENT_START_H, C.EVENT_START_H + 48, color="red", alpha=.08)
    ax.set_xlabel("Time (h)"); ax.set_ylabel("Hospital diesel stock (L)"); ax.legend(title="Package")
    ax.set_title("L2, 48 h: hospital stock under different packages")
    fig.tight_layout(); fig.savefig(OUT / "hospital_stock_L2_48h.png", dpi=160); plt.close(fig)

    # 3. Map
    fig, ax = plt.subplots(figsize=(6, 6))
    blocked = G.hazard_blocked_routes("hospital_corridor")
    for _, r in G.od_routes(C.TERMINAL_ID, C.HOSPITAL_ID).iterrows():
        p = G.route_polyline(r.route_id)
        ax.plot([x[0] for x in p], [x[1] for x in p], c="#d62728" if r.route_id in blocked else "#16803c", lw=2, label=f"{r.route_id} {'blocked' if r.route_id in blocked else 'open'}")
    h = G.hazard_polyline("hospital_corridor")
    ax.plot([x[0] for x in h], [x[1] for x in h], c="k", lw=6, label="closed segment (approx.)")
    f = G.load_facilities(); f = f[f.node_id.isin([C.TERMINAL_ID, C.HOSPITAL_ID])]
    ax.scatter(f.longitude, f.latitude, c="#1769aa", zorder=5)
    for _, r in f.iterrows(): ax.annotate(r["name"], (r.longitude, r.latitude), xytext=(5, 5), textcoords="offset points")
    ax.set_aspect(1.25); ax.legend(fontsize=8, loc="lower right"); ax.ticklabel_format(useOffset=False); ax.set_title("GIS routes Port Nelson -> Nelson Hospital (OSM)")
    fig.tight_layout(); fig.savefig(OUT / "map_L2.png", dpi=160); plt.close(fig)

    # 4. recommendation heatmap-like table
    piv = recs.pivot(index="severity", columns="duration_h", values="recommended")
    piv.to_csv(OUT.parent / "recommended_package_matrix.csv")
    print(piv)


if __name__ == "__main__":
    main()
