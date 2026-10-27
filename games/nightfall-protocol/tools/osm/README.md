# Real-world sectors from OpenStreetMap

These two scripts turn a real place into a game sector: roads, building footprints and types, land use, washes, mapped walls, named shops and services, and terrain height, all in local metres.

1. `fetch.sh <out.json> '<overpass query>'` downloads OpenStreetMap data for a bounding box from the Overpass API, retrying on dropped connections. The query used for each sector asks for buildings, highways, barriers, land use, natural features, leisure areas, waterways, amenities, shops, trees, power lines and man-made features, with geometry (`out body geom`).
2. Elevation comes from Terrain Tiles on AWS (`s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/x/y.png`): zoom 15 (about 4 m per pixel) for the sector and zoom 13 for the surrounding landscape. A second Overpass query (`context.json`) fetches major roads, towns, parks and rivers for an 8 km box around the sector.
3. `prep.py` reads both and writes `sector_<name>.json` (see `../../data/sectors/`): coordinates in metres from the sector centre (x east, z south), loot categories derived from what each place is, a 4 m height grid for the sector, and a `context` block with a 50 m height grid, major roads, towns and water for the 8 km around it.

The sectors in `data/sectors/` are 600 m squares around Anthem's town centre (Safeway, Ace Hardware, Circle K plaza) and New River (the Roadrunner, the New River wash).

## The region: a realm 100 miles square

The region is 100 miles (162 km) square, centred on the I-17 corridor (33.945 N, 112.14 W), from the Gila lowlands and Phoenix in the south to Prescott in the north. It is cut into 270 × 269 sectors of 600 m. The corridor (33.80 to 34.09 N, 112.24 to 112.04 W) is the **detail box**: 30 × 53 sectors with every building, road and track, and 100 m terrain. The rest of the realm has major roads (motorway to unclassified), towns and places, rivers and lakes, land use and points of interest, on 400 m terrain.

1. `fetch_osm.py [corridor|realm|all]` downloads the data from Overpass, one kind of feature per request: roads and buildings in quarters of the corridor, and roads, land use and points of interest in 3 × 3 tiles of the realm. It retries across the mirrors, which often answer 504 under load. Set `OVERPASS=<url>` to use only the mirror that answers from your network. It writes `reg_*.json` (corridor) and `wide_*.json` (realm) and keeps files already on disk.
2. `demfetch.py <zoom> <s> <w> <n> <e>` downloads the Terrarium elevation tiles. The realm uses zoom 10 (`python3 demfetch.py 10 33.10 -113.13 34.79 -111.15`) and the corridor zoom 13 (`python3 demfetch.py 13 33.76 -112.29 34.13 -111.99`).
3. `prep_region.py` writes `region_i17.json`; copy it to `../../data/region/`. The file holds:
   - the sectors, packed into columns (elevation range, ground type, building count; counted in the corridor, estimated from land use and sites elsewhere)
   - the realm's 400 m height grid (`dem`) and the corridor's 100 m grid (`demFine`), on one base height
   - drawable roads (`d` marks the corridor's), washes, lakes and land use
   - places and peaks, sites, the corridor's buildings
   - the travel graph

How the graph is built:
- **Merging downloads**: some downloads clip way geometry to their own box, so a road can arrive with gaps. Before splitting, every coordinate any download has for an OSM node is merged, so a clipped copy can't hide a road another file has whole. A road that still has gaps is split at them rather than dropped.
- **Shapes**: each link stores its inner points (simplified to 4 m in the corridor, 15 m elsewhere) as a fifth field, so travel on the map follows the bends.
- **Loose ends**: a dead end within 12 m of a separate piece of the network gets a short `link` edge.
- **Health check**: the script prints how many separate pieces the graph has and the share of junctions in the largest one. Check that line after a rebuild.

`prep_block.py` cuts a block of sectors out of the same download for the streaming prototype; see `../stream/README.md`.

Fetch data once per sector and keep it: the public Overpass servers have usage limits and are not meant to be queried by every player.

## Licence

Map data © OpenStreetMap contributors, available under the Open Database Licence (ODbL). The sector files are a derived database and are therefore also under the ODbL; anything that shows them must credit OpenStreetMap. Elevation data: Mapzen Terrain Tiles (see the AWS open data registry for source attributions).
