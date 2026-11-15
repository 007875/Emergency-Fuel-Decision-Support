"""
GIS data access + road-hazard logic.

Reads the OpenStreetMap-derived dataset produced by model/gis_network.py:
    gis/facilities.csv, gis/routes.csv, gis/route_segments.csv

Key idea: a hazard closes real road SEGMENTS (OSM node pairs). Any route that
uses a closed segment is blocked - so route diversity is judged on shared
segments, not on route labels.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config as C

ROOT = Path(__file__).resolve().parents[1]
GIS_DIR = ROOT / "gis"


def _need(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python model/gis_network.py")
    return path


@lru_cache(maxsize=1)
def load_facilities() -> pd.DataFrame:
    return pd.read_csv(_need(GIS_DIR / "facilities.csv"))


@lru_cache(maxsize=1)
def load_routes() -> pd.DataFrame:
    df = pd.read_csv(_need(GIS_DIR / "routes.csv"))
    df["status"] = "open"
    return df


@lru_cache(maxsize=1)
def load_segments() -> pd.DataFrame:
    df = pd.read_csv(_need(GIS_DIR / "route_segments.csv"))
    df["seg_key"] = [
        tuple(sorted((int(a), int(b)))) for a, b in zip(df["from_osm_node"], df["to_osm_node"])
    ]
    return df


def route_segment_sets() -> dict[str, set]:
    """route_id -> set of undirected road-segment keys it uses."""
    seg = load_segments()
    return {rid: set(g["seg_key"]) for rid, g in seg.groupby("route_id")}


def blocked_routes(closed_segments: set) -> set[str]:
    """Routes that use at least one closed segment."""
    return {rid for rid, s in route_segment_sets().items() if s & closed_segments}


# ----------------------------------------------------------------------------
# Route scoring (fixed: lower time / distance / risk / higher capacity = lower score)
# ----------------------------------------------------------------------------
def _minmax(series: pd.Series) -> pd.Series:
    lo, hi = float(series.min()), float(series.max())
    if hi - lo < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - lo) / (hi - lo)


@lru_cache(maxsize=1)
def scored_routes() -> pd.DataFrame:
    """All routes with a generalised cost score (0 = best) normalised per OD pair."""
    df = load_routes().copy()
    parts = []
    for _, g in df.groupby(["origin", "destination"]):
        g = g.copy()
        g["route_score"] = (
            C.W_TIME * _minmax(g["travel_time_h"])
            + C.W_DISTANCE * _minmax(g["distance_km"])
            + C.W_RISK * g["overlap_with_primary_pct"] / 100.0
            + C.W_CAPACITY * (1.0 - _minmax(g["capacity_L_h"]))
        )
        parts.append(g)
    return pd.concat(parts)


def od_routes(origin: str, destination: str) -> pd.DataFrame:
    s = scored_routes()
    return s[(s.origin == origin) & (s.destination == destination)].sort_values("alternative")


# ----------------------------------------------------------------------------
# Hazard selection - data driven, deterministic
# ----------------------------------------------------------------------------
def _segment_usage() -> dict:
    usage: dict = {}
    for rid, segs in route_segment_sets().items():
        for k in segs:
            usage.setdefault(k, set()).add(rid)
    return usage


def _longest_segment(candidates: list) -> tuple:
    seg = load_segments()
    lengths = seg.drop_duplicates("seg_key").set_index("seg_key")["length_m"]
    return max(candidates, key=lambda k: (float(lengths[k]), k))


@lru_cache(maxsize=8)
def hazard_segment(kind: str) -> tuple:
    """Pick the closed road segment for a hazard type from the real GIS network.

    alternative_exists : on the primary hospital route but NOT on any other hospital route
    hospital_corridor  : on ALL hospital routes (no road alternative) but not the port exit
    port_exit          : on every route leaving the port (regional isolation)
    """
    usage = _segment_usage()
    hosp = set(od_routes(C.TERMINAL_ID, C.HOSPITAL_ID)["route_id"])
    primary = od_routes(C.TERMINAL_ID, C.HOSPITAL_ID).iloc[0]["route_id"]
    all_routes = set(route_segment_sets())

    if kind == "alternative_exists":
        cand = [k for k, r in usage.items() if primary in r and not ((hosp - {primary}) & r)]
    elif kind == "hospital_corridor":
        cand = [k for k, r in usage.items() if hosp <= r and r != all_routes]
    elif kind == "port_exit":
        cand = [k for k, r in usage.items() if r == all_routes]
    else:
        raise ValueError(kind)
    if not cand:
        raise RuntimeError(f"No GIS segment satisfies hazard '{kind}'")
    return _longest_segment(cand)


def hazard_blocked_routes(kind: str) -> set[str]:
    return blocked_routes({hazard_segment(kind)})


# ----------------------------------------------------------------------------
# Geometry helpers (map display)
# ----------------------------------------------------------------------------
def _hav(a, b) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def route_polyline(route_id: str) -> list[list[float]]:
    row = load_routes().set_index("route_id").loc[route_id]
    return json.loads(row["geometry_json"])


def hazard_polyline(kind: str) -> list[list[float]]:
    """Approximate map position of the closed segment.

    route_segments.csv stores segment lengths but not per-segment geometry, so the
    position is located by proportional cumulative length along the route polyline.
    """
    key = hazard_segment(kind)
    seg = load_segments()
    rid = seg[seg.seg_key == key].iloc[0]["route_id"]
    rs = seg[seg.route_id == rid].sort_values("segment_number")
    total = float(rs["length_m"].sum())
    cum = rs["length_m"].cumsum().tolist()
    idx = list(rs["seg_key"]).index(key)
    start_m = 0.0 if idx == 0 else cum[idx - 1]
    end_m = cum[idx]

    poly = route_polyline(rid)
    d = [0.0]
    for a, b in zip(poly[:-1], poly[1:]):
        d.append(d[-1] + _hav(a, b))
    scale = d[-1] / total if total else 1.0
    s0, s1 = start_m * scale, end_m * scale
    out = [p for p, di in zip(poly, d) if s0 - 1e-6 <= di <= s1 + 1e-6]
    if len(out) < 2:  # very short segment: widen to neighbouring vertices
        i = min(range(len(d)), key=lambda j: abs(d[j] - (s0 + s1) / 2))
        out = poly[max(0, i - 1): i + 2]
    return out
