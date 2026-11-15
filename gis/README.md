# gis/
OpenStreetMap-derived spatial dataset (Nelson, NZ), built once by `python model/gis_network.py`
(needs internet; the OSMnx cache is kept in `cache/`).

- `facilities.csv`  geocoded facility locations (the demand/inventory columns here are legacy and NOT used;
  all operational assumptions are in `model/config.py`)
- `routes.csv`      3 diverse road routes per origin-destination pair, with polyline geometry
- `route_segments.csv`  OSM node-pair segments per route (used to decide which routes a closed segment blocks)
- `gis_metadata.csv`    provenance
