from __future__ import annotations

import json

from pathlib import Path
from typing import Dict, List, Tuple

import networkx as nx
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
GIS_DIR = BASE_DIR / "gis"
GIS_DIR.mkdir(exist_ok=True)

# Nelson–Tasman proof-of-concept study area.
# Facility coordinates are NOT stored here: they are obtained from OpenStreetMap/Nominatim.
STUDY_PLACE = "Nelson, New Zealand"
STUDY_CENTER = (-41.2710849, 173.2836756)  # geocoded Nelson centre; used only as download centre
STUDY_RADIUS_M = 18000

# These are search descriptions, not hand-entered coordinates.
# The GIS service resolves the locations and the road network connects them.
FACILITIES = [
    {
        "node_id": "PORT_01",
        "name": "Port Nelson",
        "node_type": "port",
        "query": "Port Nelson, Nelson, New Zealand",
        "demand_type": "none",
        "demand_rate": 0,
        "priority": 0,
        "initial_inventory": 0,
    },
    {
        "node_id": "CRIT_01",
        "name": "Nelson Hospital",
        "node_type": "critical",
        "query": "Nelson Hospital, Nelson, New Zealand",
        "demand_type": "critical",
        "demand_rate": 500,
        "priority": 1,
        "initial_inventory": 2000,
    },
    {
        "node_id": "FS_01",
        "name": "Fuel Station 1",
        "node_type": "fuel_station",
        "query": "fuel station near Nelson, New Zealand",
        "demand_type": "general",
        "demand_rate": 800,
        "priority": 3,
        "initial_inventory": 4000,
    },
    {
        "node_id": "FS_02",
        "name": "Fuel Station 2",
        "node_type": "fuel_station",
        "query": "fuel station near Richmond, Tasman, New Zealand",
        "demand_type": "general",
        "demand_rate": 600,
        "priority": 3,
        "initial_inventory": 3000,
    },
    {
        "node_id": "FS_03",
        "name": "Fuel Station 3",
        "node_type": "fuel_station",
        "query": "fuel station near Stoke, Nelson, New Zealand",
        "demand_type": "general",
        "demand_rate": 500,
        "priority": 3,
        "initial_inventory": 2500,
    },
]


def geocode_facilities() -> pd.DataFrame:
    """Resolve facility locations through Nominatim using OSMnx.

    Important: we use point geocoding here rather than geocode_to_gdf(), because
    several facilities are returned as points rather than polygons.
    """
    import osmnx as ox

    print("[1/5] Geocoding facilities with OpenStreetMap/Nominatim...", flush=True)
    rows = []
    for f in FACILITIES:
        try:
            lat, lon = ox.geocode(f["query"])
            lat, lon = float(lat), float(lon)
        except Exception as exc:
            raise RuntimeError(
                f"Could not geocode {f['name']} ({f['query']}): {exc}"
            ) from exc

        row = dict(f)
        row.pop("query")
        row["latitude"] = lat
        row["longitude"] = lon
        rows.append(row)
        print(f"    ✓ {f['name']}: {lat:.6f}, {lon:.6f}", flush=True)

    return pd.DataFrame(rows)


def download_drive_network():
    """Download a real drivable road network from OpenStreetMap."""
    import osmnx as ox

    print(
        f"[2/5] Downloading drivable OSM road network ({STUDY_RADIUS_M/1000:.0f} km radius)...",
        flush=True,
    )
    ox.settings.use_cache = True
    ox.settings.log_console = False

    # graph_from_point is deliberately used instead of graph_from_place because
    # it is faster and more predictable for this small proof-of-concept study area.
    G = ox.graph_from_point(
        STUDY_CENTER,
        dist=STUDY_RADIUS_M,
        network_type="drive",
        simplify=True,
    )

    # Add speed and travel-time attributes from OSM data / OSMnx defaults.
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

    print(f"    ✓ {len(G.nodes):,} road nodes / {len(G.edges):,} road edges", flush=True)
    return G


def nearest_node_map(G, facilities: pd.DataFrame) -> Dict[str, int]:
    import osmnx as ox

    print("[3/5] Connecting GIS facilities to the nearest road nodes...", flush=True)
    mapping: Dict[str, int] = {}
    for _, row in facilities.iterrows():
        node = ox.distance.nearest_nodes(
            G,
            X=float(row["longitude"]),
            Y=float(row["latitude"]),
        )
        mapping[row["node_id"]] = node
        print(f"    ✓ {row['name']} → road node {node}", flush=True)
    return mapping


def _edge_distance_m(data: dict) -> float:
    try:
        return max(float(data.get("length", 1.0)), 1.0)
    except (TypeError, ValueError):
        return 1.0


def _edge_capacity_l_h(data: dict) -> float:
    """Illustrative route throughput based on OSM road class.

    This is NOT a claim about actual tanker capacity or road legal capacity.
    It is a transparent modelling parameter for the proof-of-concept.
    """
    highway = data.get("highway")
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    return {
        "motorway": 5000,
        "trunk": 4500,
        "primary": 3500,
        "secondary": 2500,
        "tertiary": 1800,
        "unclassified": 1400,
        "residential": 1000,
        "service": 500,
    }.get(highway, 1200)


def _build_simple_graph(G):
    """Collapse OSM MultiDiGraph to one directed edge per node pair.

    For routing, the edge with the lowest travel time is retained. Its OSM
    geometry and attributes are carried into the simplified graph.
    """
    H = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        travel_s = float(data.get("travel_time", 0.0) or 0.0)
        if travel_s <= 0:
            travel_s = _edge_distance_m(data) / 1000 / 40 * 3600

        candidate = {
            "distance_m": _edge_distance_m(data),
            "travel_time_h": travel_s / 3600,
            "capacity_l_h": _edge_capacity_l_h(data),
            "geometry": data.get("geometry"),
            "highway": data.get("highway"),
        }

        if not H.has_edge(u, v) or candidate["travel_time_h"] < H[u][v]["travel_time_h"]:
            H.add_edge(u, v, **candidate)

    return H


def _path_geometry(G, path: List[int]) -> List[List[float]]:
    """Recover OSM geometry for a route as [[lon, lat], ...]."""
    coords: List[List[float]] = []

    for a, b in zip(path[:-1], path[1:]):
        edge_data = G.get_edge_data(a, b)
        if not edge_data:
            continue

        # Choose the shortest edge if multiple OSM edges exist.
        best = min(edge_data.values(), key=lambda d: _edge_distance_m(d))
        geom = best.get("geometry")

        if geom is not None:
            segment = [[float(x), float(y)] for x, y in geom.coords]
        else:
            segment = [
                [float(G.nodes[a]["x"]), float(G.nodes[a]["y"])],
                [float(G.nodes[b]["x"]), float(G.nodes[b]["y"])],
            ]

        if coords and segment and coords[-1] == segment[0]:
            coords.extend(segment[1:])
        else:
            coords.extend(segment)

    return coords


def _route_edges(path: List[int]) -> List[Tuple[int, int]]:
    return list(zip(path[:-1], path[1:]))


def _route_overlap_pct(route_a: List[Tuple[int, int]], route_b: List[Tuple[int, int]]) -> float:
    """Percentage of route A's road segments also used by route B."""
    if not route_a:
        return 0.0
    a = set(route_a)
    b = set(route_b)
    return 100.0 * len(a.intersection(b)) / len(a)


def _find_diverse_routes(H, source: int, target: int, max_routes: int = 3) -> List[List[int]]:
    """Find shortest routes while rejecting near-duplicate alternatives."""
    try:
        generator = nx.shortest_simple_paths(H, source, target, weight="distance_m")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    candidates = []
    shortest_distance = None

    for path in generator:
        distance_m = sum(H[a][b]["distance_m"] for a, b in _route_edges(path))
        if distance_m <= 0:
            continue
        if shortest_distance is None:
            shortest_distance = distance_m
        if distance_m > shortest_distance * 2.5:
            break
        candidates.append(path)
        if len(candidates) >= 40:
            break

    if not candidates:
        return []

    selected = [candidates[0]]

    # Progressively relax the diversity requirement if the network does not
    # contain three sufficiently independent alternatives.
    for threshold in (70.0, 80.0, 90.0, 100.0):
        for candidate in candidates[1:]:
            if len(selected) >= max_routes:
                break
            candidate_edges = _route_edges(candidate)
            too_similar = False
            for existing in selected:
                overlap = _route_overlap_pct(candidate_edges, _route_edges(existing))
                if overlap > threshold:
                    too_similar = True
                    break
            if not too_similar:
                selected.append(candidate)
        if len(selected) >= max_routes:
            break

    return selected[:max_routes]


def build_route_links(G, facilities: pd.DataFrame, facility_nodes: Dict[str, int]) -> pd.DataFrame:
    """Generate GIS-derived route alternatives and route-overlap metrics."""
    print("[4/5] Generating alternative GIS routes...", flush=True)

    H = _build_simple_graph(G)
    pairs = [
        ("PORT_01", "CRIT_01"),
        ("PORT_01", "FS_01"),
        ("PORT_01", "FS_02"),
        ("PORT_01", "FS_03"),
    ]

    rows = []
    segment_rows = []
    route_index = 0

    for origin, destination in pairs:
        if origin not in facility_nodes or destination not in facility_nodes:
            print(f"    ! Skipping route {origin} → {destination}: facility not available", flush=True)
            continue

        source = facility_nodes[origin]
        target = facility_nodes[destination]
        paths = _find_diverse_routes(H, source, target, max_routes=3)

        if not paths:
            print(f"    ! No road path: {origin} → {destination}", flush=True)
            continue

        primary_edges = _route_edges(paths[0])

        for alternative, path in enumerate(paths, start=1):
            edges = _route_edges(path)
            distance_m = sum(H[a][b]["distance_m"] for a, b in edges)
            travel_h = sum(H[a][b]["travel_time_h"] for a, b in edges)
            capacity = min(H[a][b]["capacity_l_h"] for a, b in edges)
            geometry = _path_geometry(G, path)
            if not geometry:
                continue

            route_index += 1
            route_id = f"R{route_index:02d}"
            overlap = _route_overlap_pct(edges, primary_edges)

            rows.append({
                "route_id": route_id,
                "origin": origin,
                "destination": destination,
                "alternative": alternative,
                "distance_km": round(distance_m / 1000, 3),
                "travel_time_h": round(travel_h, 3),
                "capacity_L_h": round(float(capacity), 0),
                "overlap_with_primary_pct": round(overlap, 1),
                "status": "open",
                "num_road_segments": len(edges),
                "geometry_json": json.dumps(geometry),
            })

            for segment_number, (a, b) in enumerate(edges, start=1):
                segment_rows.append({
                    "route_id": route_id,
                    "segment_number": segment_number,
                    "from_osm_node": int(a),
                    "to_osm_node": int(b),
                    "length_m": round(H[a][b]["distance_m"], 2),
                    "travel_time_s": round(H[a][b]["travel_time_h"] * 3600, 2),
                    "capacity_L_h": round(float(H[a][b]["capacity_l_h"]), 0),
                    "highway": str(H[a][b].get("highway", "unknown")),
                })

        print(f"    ✓ {origin} → {destination}: {len(paths)} route alternatives", flush=True)

    routes = pd.DataFrame(rows)
    segments = pd.DataFrame(segment_rows)
    return routes, segments


def build_gis_dataset() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build and persist the GIS-derived dataset used by the dashboard/model."""
    facilities = geocode_facilities()
    G = download_drive_network()
    mapping = nearest_node_map(G, facilities)
    routes, segments = build_route_links(G, facilities, mapping)

    if routes.empty:
        raise RuntimeError("No GIS-derived routes were generated.")

    print("[5/5] Saving GIS-derived dataset...", flush=True)
    facilities.to_csv(GIS_DIR / "facilities.csv", index=False, encoding="utf-8")
    routes.to_csv(GIS_DIR / "routes.csv", index=False, encoding="utf-8")
    segments.to_csv(GIS_DIR / "route_segments.csv", index=False, encoding="utf-8")

    pd.DataFrame([{
        "source": "OpenStreetMap",
        "geocoding": "Nominatim via OSMnx",
        "study_place": STUDY_PLACE,
        "study_radius_m": STUDY_RADIUS_M,
        "network_type": "drive",
        "route_method": "diverse shortest simple paths by road distance",
        "route_count_per_od": 3,
        "capacity_note": "Illustrative model parameter; not real tanker/road capacity",
    }]).to_csv(GIS_DIR / "gis_metadata.csv", index=False, encoding="utf-8")

    print("DONE — GIS dataset ready for the decision model.", flush=True)
    return facilities, routes


if __name__ == "__main__":
    facilities, routes = build_gis_dataset()
    print("\nFacilities:")
    print(facilities[["node_id", "name", "node_type", "latitude", "longitude"]].to_string(index=False))
    print("\nRoutes:")
    print(routes[[
        "route_id", "origin", "destination", "alternative",
        "distance_km", "travel_time_h", "capacity_L_h",
        "overlap_with_primary_pct", "status"
    ]].to_string(index=False))
