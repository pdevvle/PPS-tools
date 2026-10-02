# Real-world sectors from OpenStreetMap

These two scripts turn a real place into a game sector: roads, building footprints and types, land use, washes, mapped walls, named shops and services, and terrain height, all in local metres.

1. `fetch.sh <out.json> '<overpass query>'` downloads OpenStreetMap data for a bounding box from the Overpass API, retrying on dropped connections. The query used for each sector asks for buildings, highways, barriers, land use, natural features, leisure areas, waterways, amenities, shops, trees, power lines and man-made features, with geometry (`out body geom`).
2. Elevation comes from Terrain Tiles on AWS (`s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/x/y.png`): zoom 15 (about 4 m per pixel) for the sector and zoom 13 for the surrounding landscape. A second Overpass query (`context.json`) fetches major roads, towns, parks and rivers for an 8 km box around the sector.
3. `prep.py` reads both and writes `sector_<name>.json` (see `../../data/sectors/`): coordinates in metres from the sector centre (x east, z south), loot categories derived from what each place is, a 4 m height grid for the sector, and a `context` block with a 50 m height grid, major roads, towns and water for the 8 km around it.

The sectors in `data/sectors/` are 600 m squares around Anthem's town centre (Safeway, Ace Hardware, Circle K plaza) and New River (the Roadrunner, the New River wash).

## The pilot region

`regionfetch.sh` downloads the region box (33.80 to 34.09 N, 112.24 to 112.04 W) from Overpass in eight tiles, retrying each until the server answers. `prep_region.py` merges those tiles with the earlier sector downloads and writes `../../data/region/region_i17.json`: a 600 m sector grid with building counts, sites, elevation range and ground type per sector; a 100 m height grid with a 3 km apron; drawable roads, washes, lakes and land use; towns and peaks; and a travel graph built by splitting roads at shared OSM nodes. The committed file was built while only part of the region had downloaded, so the south-west tile and the Anthem and New River surroundings are complete and the rest has terrain only; rerun both scripts to fill it in.

Fetch data once per sector and keep it: the public Overpass servers have usage limits and are not meant to be queried by every player.

## Licence

Map data © OpenStreetMap contributors, available under the Open Database Licence (ODbL). The sector files are a derived database and are therefore also under the ODbL; anything that shows them must credit OpenStreetMap. Elevation data: Mapzen Terrain Tiles (see the AWS open data registry for source attributions).
