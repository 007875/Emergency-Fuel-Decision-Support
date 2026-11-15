"""
Central assumptions for the emergency diesel decision-support prototype.

EVERY number in this file is an ILLUSTRATIVE modelling assumption.
They exist to make the model structure runnable and transparent. In the PhD
they would be replaced by validated fuel-sector, road, hazard and stakeholder
data (see README -> "What would be replaced in the PhD").

Facility *locations* and road *geometry* are NOT here: they come from the
OpenStreetMap GIS dataset in gis/ (built by model/gis_network.py).
"""
from __future__ import annotations

# ----------------------------------------------------------------------------
# Time
# ----------------------------------------------------------------------------
DT_H = 0.25                 # simulation time step (h)
HORIZON_H = 120.0           # total simulated time (h)
EVENT_START_H = 6.0         # hazard event hits at this time (normal operation before)
RECOVERY_WINDOW_H = 24.0    # KPIs are measured from event start to event end + this

# ----------------------------------------------------------------------------
# Supply chain tier 1-2: import terminal / bulk storage (Port Nelson node)
# ----------------------------------------------------------------------------
TERMINAL_ID = "PORT_01"
TERMINAL_CAPACITY_L = 150_000.0
TERMINAL_INITIAL_L = 60_000.0
INBOUND_SUPPLY_L_H = 2_000.0          # normal national/coastal resupply into the terminal
OTHER_REGIONAL_DRAW_L_H = 1_000.0     # exogenous demand on the terminal from customers not modelled
LOADOUT_CAPACITY_L_H = 3_000.0        # truck loading-rack throughput when grid is up
LOADOUT_FACTOR_GRID_DOWN = 0.5        # fraction of loadout available on terminal backup power
FLEET_CAPACITY_L_H = 4_000.0          # total tanker fleet throughput (all destinations)
TANKER_PAYLOAD_L = 20_000.0           # used only for transport cost (trips)
TRANSPORT_COST_NZD_PER_KM = 2.8       # illustrative tanker operating cost per loaded+return km

# ----------------------------------------------------------------------------
# Tier 3-4: critical customer and retail sites (locations come from GIS)
# ----------------------------------------------------------------------------
HOSPITAL_ID = "CRIT_01"
HOSPITAL_TANK_L = 6_000.0
HOSPITAL_INITIAL_L = 4_500.0
HOSPITAL_DEMAND_GRID_UP_L_H = 10.0    # standby/testing only
HOSPITAL_DEMAND_GRID_DOWN_L_H = 150.0 # backup generators carry the site  <-- electricity dependency
HOSPITAL_TARGET_COVER_H = 48.0

RETAIL_SITES = {
    # node_id: dict(demand L/h, tank L, initial L, has_backup_power)
    "FS_01": dict(demand=300.0, tank=12_000.0, initial=9_000.0, backup=True),
    "FS_02": dict(demand=250.0, tank=10_000.0, initial=7_500.0, backup=False),
    "FS_03": dict(demand=200.0, tank=8_000.0,  initial=6_000.0, backup=False),
}
RETAIL_CRITICAL_SHARE = 0.15          # share of retail diesel taken by emergency/lifeline/food fleets
RETAIL_TARGET_COVER_H = 36.0

# ----------------------------------------------------------------------------
# Route scoring (generalised cost used when choosing an alternative route)
# lower = better; all components are min-max normalised within an OD pair
# ----------------------------------------------------------------------------
W_TIME, W_DISTANCE, W_RISK, W_CAPACITY = 0.45, 0.25, 0.15, 0.15

# ----------------------------------------------------------------------------
# Interventions (what the decision-maker can switch on)
# lag_h = delay after the event before the action is effective
# feasibility: 1 (hard) .. 5 (easy). PLACEHOLDER for stakeholder elicitation.
# ----------------------------------------------------------------------------
INTERVENTIONS = {
    "A": dict(name="Demand prioritisation", lag_h=2.0, feasibility=3),
    "B": dict(name="Pre-positioning", lag_h=0.0, feasibility=5),
    "C": dict(name="Rerouting", lag_h=0.5, feasibility=4),
    "D": dict(name="Coastal shipping", lag_h=24.0, feasibility=2),
    "E": dict(name="NZDF / commercial support", lag_h=12.0, feasibility=3),
}
# A: demand prioritisation
GENERAL_RATION_FACTOR = 0.5           # general retail + other regional draw cut to 50 %
PRIORITY_ACCESS_COST_FIXED_NZD = 5_000.0
PRIORITY_ACCESS_COST_NZD_PER_H = 600.0   # designated-site portable power, while grid is down
# B: pre-positioning
PREPOSITION_VOLUME_L = 5_000.0           # portable bladder tank at the hospital
PREPOSITION_COST_FIXED_NZD = 2_500.0
PREPOSITION_COST_NZD_PER_L = 0.25        # handling / lease, NOT the fuel itself (fuel is consumed)
# D: coastal shipping
SHIPPING_VOLUME_L = 100_000.0
SHIPPING_COST_FIXED_NZD = 40_000.0
SHIPPING_COST_NZD_PER_L = 0.06
# E: NZDF / commercial alternative mode (e.g. helicopter / 4WD) port -> hospital
ALT_MODE_CAPACITY_L_H = 600.0
ALT_MODE_TRAVEL_H = 0.5
ALT_MODE_COST_NZD_PER_H = 6_000.0

# ----------------------------------------------------------------------------
# Hazard severity levels (the "scenarios of varying severity and duration")
# road_hazard: which GIS road segment is closed (selected from the real GIS network)
# elec_factor: electricity outage duration = factor * road-closure duration
# inbound_cut: national/coastal resupply into the terminal stops during the event
# ----------------------------------------------------------------------------
SEVERITIES = {
    "L1": dict(label="L1 Localised road damage", road_hazard="alternative_exists",
               elec_factor=0.5, inbound_cut=False),
    "L2": dict(label="L2 Corridor closure", road_hazard="hospital_corridor",
               elec_factor=1.0, inbound_cut=False),
    "L3": dict(label="L3 Regional isolation", road_hazard="port_exit",
               elec_factor=1.5, inbound_cut=True),
}
DURATIONS_H = [12, 24, 48, 72]

# Decision rule used for the recommendation
TARGET_CRITICAL_SERVICE_PCT = 97.0
MIN_FEASIBILITY = 3
