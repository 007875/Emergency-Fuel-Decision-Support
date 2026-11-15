"""
Single simulation engine for the emergency diesel prototype.

Supply chain represented (mini version of the national -> regional structure):

    import / coastal supply -> terminal + bulk storage (Port Nelson)
        -> road distribution over the GIS network (real OSM routes)
        -> critical customer (hospital) and retail sites (with a critical-fleet share)

Disruptions: closed road segment(s), electricity outage, inbound-supply cut.
Dependencies: grid outage raises hospital diesel demand (generators), halves
terminal loadout, and stops pumps at stations without backup power.
Interventions: A prioritisation, B pre-positioning, C rerouting,
               D coastal shipping, E NZDF/commercial alternative mode.

All parameters are illustrative -> model/config.py.
"""
from __future__ import annotations

from itertools import combinations

import pandas as pd

from . import config as C
from . import gis_data as G

RETAIL_ORDER = list(C.RETAIL_SITES)


def combo_label(ints: frozenset | set) -> str:
    return "+".join(sorted(ints)) if ints else "None"


def all_combos() -> list[frozenset]:
    keys = sorted(C.INTERVENTIONS)
    out = []
    for r in range(len(keys) + 1):
        out += [frozenset(c) for c in combinations(keys, r)]
    return out


def combo_feasibility(ints) -> int:
    return min([C.INTERVENTIONS[i]["feasibility"] for i in ints], default=5)


def _route_choice(od: pd.DataFrame, closed: set, reroute_on: bool):
    """Return (route_row or None). Primary = alternative 1."""
    primary = od.iloc[0]
    if primary["route_id"] not in closed:
        return primary
    if not reroute_on:
        return None
    avail = od[~od["route_id"].isin(closed)].sort_values("route_score")
    return None if avail.empty else avail.iloc[0]


def simulate(severity: str, duration_h: float, interventions=frozenset(), record: bool = True):
    sev = C.SEVERITIES[severity]
    ints = frozenset(interventions)
    dt = C.DT_H
    es = C.EVENT_START_H
    road_end = es + duration_h
    elec_end = es + duration_h * sev["elec_factor"]
    event_end = max(road_end, elec_end)
    kpi_end = event_end + C.RECOVERY_WINDOW_H

    closed_all = G.hazard_blocked_routes(sev["road_hazard"])
    hosp_od = G.od_routes(C.TERMINAL_ID, C.HOSPITAL_ID)
    ret_od = {n: G.od_routes(C.TERMINAL_ID, n) for n in RETAIL_ORDER}
    primary_km = {C.HOSPITAL_ID: float(hosp_od.iloc[0]["distance_km"])}
    primary_km.update({n: float(ret_od[n].iloc[0]["distance_km"]) for n in RETAIL_ORDER})

    act = {k: es + v["lag_h"] for k, v in C.INTERVENTIONS.items()}

    # --- state
    term = C.TERMINAL_INITIAL_L
    hosp_cap = C.HOSPITAL_TANK_L + (C.PREPOSITION_VOLUME_L if "B" in ints else 0.0)
    hosp = C.HOSPITAL_INITIAL_L + (C.PREPOSITION_VOLUME_L if "B" in ints else 0.0)
    retail = {n: C.RETAIL_SITES[n]["initial"] for n in RETAIL_ORDER}
    pending: list[tuple[float, str, float]] = []   # (arrival_h, dest, litres)
    shipped = False

    # --- accumulators (KPI window only)
    crit_dem = crit_unmet = gen_dem = gen_unmet = 0.0
    hosp_short_h = 0.0
    hosp_min = hosp
    term_min = term
    first_short = None
    cost_reroute = cost_alt = cost_prior_var = 0.0
    rows = []

    n_steps = int(C.HORIZON_H / dt)
    for i in range(n_steps):
        t = round(i * dt, 6)
        road_closed = es <= t < road_end
        grid_down = es <= t < elec_end
        inbound_cut = sev["inbound_cut"] and es <= t < road_end
        in_window = es <= t < kpi_end
        closed = closed_all if road_closed else set()
        a_on = "A" in ints and act["A"] <= t < event_end
        c_on = "C" in ints and t >= act["C"]
        e_on = "E" in ints and act["E"] <= t < event_end

        # 1. arrivals
        still = []
        for arr, dest, q in pending:
            if arr <= t + 1e-9:
                if dest == C.HOSPITAL_ID:
                    hosp = min(hosp_cap, hosp + q)
                else:
                    retail[dest] = min(C.RETAIL_SITES[dest]["tank"], retail[dest] + q)
            else:
                still.append((arr, dest, q))
        pending = still

        # 2. terminal: resupply, shipping, regional draw
        if not inbound_cut:
            term = min(C.TERMINAL_CAPACITY_L, term + C.INBOUND_SUPPLY_L_H * dt)
        if "D" in ints and not shipped and t >= act["D"]:
            term = min(C.TERMINAL_CAPACITY_L, term + C.SHIPPING_VOLUME_L)
            shipped = True
        other = C.OTHER_REGIONAL_DRAW_L_H * dt * (C.GENERAL_RATION_FACTOR if a_on else 1.0)
        term = max(0.0, term - min(term, other))

        # 3. dispatch (priority: hospital first, then retail)
        loadout = C.LOADOUT_CAPACITY_L_H * dt * (C.LOADOUT_FACTOR_GRID_DOWN if grid_down else 1.0)
        fleet = C.FLEET_CAPACITY_L_H * dt
        in_transit = lambda d: sum(q for _, dd, q in pending if dd == d)

        # hospital
        h_target = min(hosp_cap, C.HOSPITAL_TARGET_COVER_H * C.HOSPITAL_DEMAND_GRID_DOWN_L_H
                       + (C.PREPOSITION_VOLUME_L if "B" in ints else 0.0))
        h_need = max(0.0, h_target - hosp - in_transit(C.HOSPITAL_ID))
        route = _route_choice(hosp_od, closed, c_on)
        h_route_id = None if route is None else route["route_id"]
        if route is not None and h_need > 0:
            q = min(h_need, float(route["capacity_L_h"]) * dt, fleet, loadout, term)
            if q > 1e-9:
                pending.append((t + float(route["travel_time_h"]), C.HOSPITAL_ID, q))
                term -= q; fleet -= q; loadout -= q
                extra = max(0.0, float(route["distance_km"]) - primary_km[C.HOSPITAL_ID])
                cost_reroute += q / C.TANKER_PAYLOAD_L * 2 * extra * C.TRANSPORT_COST_NZD_PER_KM
        alt_used = False
        if e_on and route is None and h_need > 0:
            q = min(h_need, C.ALT_MODE_CAPACITY_L_H * dt, term)
            if q > 1e-9:
                pending.append((t + C.ALT_MODE_TRAVEL_H, C.HOSPITAL_ID, q))
                term -= q
                alt_used = True
                cost_alt += C.ALT_MODE_COST_NZD_PER_H * dt

        # retail
        for n in RETAIL_ORDER:
            s = C.RETAIL_SITES[n]
            target = min(s["tank"], C.RETAIL_TARGET_COVER_H * s["demand"])
            need = max(0.0, target - retail[n] - in_transit(n))
            r = _route_choice(ret_od[n], closed, c_on)
            if r is not None and need > 0:
                q = min(need, float(r["capacity_L_h"]) * dt, fleet, loadout, term)
                if q > 1e-9:
                    pending.append((t + float(r["travel_time_h"]), n, q))
                    term -= q; fleet -= q; loadout -= q
                    extra = max(0.0, float(r["distance_km"]) - primary_km[n])
                    cost_reroute += q / C.TANKER_PAYLOAD_L * 2 * extra * C.TRANSPORT_COST_NZD_PER_KM

        # 4. consumption / dispensing
        h_dem = (C.HOSPITAL_DEMAND_GRID_DOWN_L_H if grid_down else C.HOSPITAL_DEMAND_GRID_UP_L_H) * dt
        h_srv = min(hosp, h_dem)
        hosp -= h_srv
        h_unmet = h_dem - h_srv

        c_dem_step = c_unmet_step = g_dem_step = g_unmet_step = 0.0
        c_dem_step += h_dem; c_unmet_step += h_unmet
        for n in RETAIL_ORDER:
            s = C.RETAIL_SITES[n]
            d = s["demand"] * dt
            dc, dg = d * C.RETAIL_CRITICAL_SHARE, d * (1 - C.RETAIL_CRITICAL_SHARE)
            power_ok = (not grid_down) or s["backup"] or ("F" in ints)
            crit_cap = dc if (power_ok or a_on) else 0.0
            gen_cap = dg * (C.GENERAL_RATION_FACTOR if a_on else 1.0) if power_ok else 0.0
            sc = min(retail[n], crit_cap); retail[n] -= sc
            sg = min(retail[n], gen_cap); retail[n] -= sg
            c_dem_step += dc; c_unmet_step += dc - sc
            g_dem_step += dg; g_unmet_step += dg - sg

        if in_window:
            crit_dem += c_dem_step; crit_unmet += c_unmet_step
            gen_dem += g_dem_step; gen_unmet += g_unmet_step
            if h_unmet > 1e-9:
                hosp_short_h += dt
            if c_unmet_step > 1e-9 and first_short is None:
                first_short = t - es
        hosp_min = min(hosp_min, hosp) if in_window else hosp_min
        term_min = min(term_min, term) if in_window else term_min

        if record:
            rows.append(dict(
                time_h=t, hospital_L=hosp, terminal_L=term, retail_L=sum(retail.values()),
                critical_unmet_L=c_unmet_step, general_unmet_L=g_unmet_step,
                hospital_route=h_route_id, alt_mode_used=alt_used,
                road_closed=road_closed, grid_down=grid_down,
            ))

    # --- intervention costs
    cost = 0.0
    if "A" in ints:
        cost += C.PRIORITY_ACCESS_COST_FIXED_NZD
        cost += C.PRIORITY_ACCESS_COST_NZD_PER_H * max(0.0, min(elec_end, event_end) - act["A"])
    if "B" in ints:
        cost += C.PREPOSITION_COST_FIXED_NZD + C.PREPOSITION_COST_NZD_PER_L * C.PREPOSITION_VOLUME_L
    if "D" in ints:
        cost += C.SHIPPING_COST_FIXED_NZD + C.SHIPPING_COST_NZD_PER_L * C.SHIPPING_VOLUME_L
    cost += cost_reroute + cost_alt

    summary = dict(
        severity=severity, duration_h=duration_h, interventions=combo_label(ints),
        n_interventions=len(ints),
        critical_demand_L=crit_dem, critical_unmet_L=crit_unmet,
        critical_met_pct=100.0 * (1 - crit_unmet / crit_dem) if crit_dem else 100.0,
        hospital_shortage_h=hosp_short_h, hospital_min_inventory_L=hosp_min,
        first_shortage_h_after_event=first_short,
        general_demand_L=gen_dem, general_unmet_L=gen_unmet,
        general_met_pct=100.0 * (1 - gen_unmet / gen_dem) if gen_dem else 100.0,
        terminal_min_L=term_min,
        intervention_cost_nzd=cost, feasibility=combo_feasibility(ints),
    )
    return summary, (pd.DataFrame(rows) if record else None)
