"""
Simulation experiments: severity x duration x intervention combinations.

    python -m model.experiments

Outputs (results/):
    experiment_grid.csv    every run (3 severities x 4 durations x 32 combinations)
    recommendations.csv    cheapest feasible combination meeting the service target
    pareto_front.csv       non-dominated combinations (unmet critical demand vs cost)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config as C
from .fuel_sim import all_combos, simulate

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


def run_combos(severity: str, duration_h: float) -> pd.DataFrame:
    return pd.DataFrame([simulate(severity, duration_h, c, record=False)[0] for c in all_combos()])


def pareto_flag(df: pd.DataFrame) -> pd.Series:
    """Non-dominated on (critical_unmet_L, intervention_cost_nzd); both minimised."""
    flags = []
    for i, r in df.iterrows():
        dominated = (
            (df.critical_unmet_L <= r.critical_unmet_L + 1e-9)
            & (df.intervention_cost_nzd <= r.intervention_cost_nzd + 1e-9)
            & ((df.critical_unmet_L < r.critical_unmet_L - 1e-9)
               | (df.intervention_cost_nzd < r.intervention_cost_nzd - 1e-9))
        ).any()
        flags.append(not dominated)
    return pd.Series(flags, index=df.index)


def recommend(df: pd.DataFrame, target=C.TARGET_CRITICAL_SERVICE_PCT, min_feas=C.MIN_FEASIBILITY):
    """Cheapest combo meeting the target at acceptable feasibility; else best achievable."""
    ok = df[(df.critical_met_pct >= target) & (df.feasibility >= min_feas)]
    if not ok.empty:
        return ok.sort_values(["intervention_cost_nzd", "general_unmet_L"]).iloc[0], True
    feas = df[df.feasibility >= min_feas]
    pool = feas if not feas.empty else df
    return pool.sort_values(["critical_met_pct", "intervention_cost_nzd"], ascending=[False, True]).iloc[0], False


def run_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    parts, recs = [], []
    for sev in C.SEVERITIES:
        for dur in C.DURATIONS_H:
            df = run_combos(sev, dur)
            df["pareto"] = pareto_flag(df)
            parts.append(df)
            best, met = recommend(df)
            base = df[df.interventions == "None"].iloc[0]
            recs.append(dict(
                severity=sev, duration_h=dur,
                baseline_critical_met_pct=base.critical_met_pct,
                recommended=best.interventions, target_met=met,
                critical_met_pct=best.critical_met_pct,
                intervention_cost_nzd=best.intervention_cost_nzd,
                general_met_pct=best.general_met_pct, feasibility=best.feasibility,
            ))
    grid = pd.concat(parts, ignore_index=True)
    return grid, pd.DataFrame(recs)


def main():
    RESULTS_DIR.mkdir(exist_ok=True)
    grid, recs = run_all()
    grid.to_csv(RESULTS_DIR / "experiment_grid.csv", index=False)
    recs.to_csv(RESULTS_DIR / "recommendations.csv", index=False)
    grid[grid.pareto].to_csv(RESULTS_DIR / "pareto_front.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"{len(grid)} runs\n")
    print(recs.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
