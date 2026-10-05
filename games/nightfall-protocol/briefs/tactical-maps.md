# Brief: tactical maps

Read `00-foundation.md` first.

## Goal

The real ground at walking scale, everywhere in the region: baked offline from OpenStreetMap and elevation, streamed around the squad without hitches, with common-sense terrain, water, roads, bridges and buildings.

## Where it stands

- Pipeline: `tools/osm/fetch.sh`, `regionfetch.sh` (region download in 8 tiles; 7 are in, the south-east one keeps failing), `prep.py` (single sectors), `prep_block.py` (a block of sectors), `tools/stream/bake.js` with `sector-core.js` (shaping and placement shared by the bake and the browser), `tools/stream/stream-main.js` (streaming runtime). See `tools/stream/README.md` and `tools/osm/README.md`.
- `mockups/real-sectors.html`: two hand-built sectors (Anthem, New River) with the most visual detail: washes that run downhill, a flat-level lake basin, pools, culverts, bridges with an undercroft, a movement cost overlay, swim gear.
- `mockups/streaming/`: the New River block (5 × 5 sectors) baked and streamed 3 × 3 around the squad; centre sector with ink and full plants, ring lighter; paths across edges.
- Roads (`tools/stream/roads-bake.js`, `road-kit.js`, data in `data/roads/`): textured asphalt, concrete, gravel, dirt and sand; lane paint from OSM lanes and turn lanes; junction boxes; stop signs with street-name blades, speed limits, exit 232 gore and guide signs, I-17 shields, do-not-enter signs, inferred mast-arm signals at the south-west ramp terminals; the cable median barrier, delineators, rumble strips, gates, cattle guards, grader berms, rock cuts; and the 217 driveways, tracks and paths the region download missed.
- Measured (software rendering): 45–80 ms to build a sector, longest single step 115–180 ms, about 40 ms to move the centre, 3 × 3 window about 360 draw calls and 2.2 M triangles, about 175 KB per sector compressed.

## Decisions (keep)

- Shape a whole block at once so sector edges match; ship per-sector files; build meshes in the browser a step at a time.
- 2 m movement grid with terrain speeds (foundation), a deck layer per bridge, water closed without swim gear.
- Bridges from OSM bridge tags: dig under the deck for headroom first, raise the deck and ramp the approaches for the rest. Washes over 3.4 m plus deck depth (an undercroft people can walk in); roads 5.3 m.
- Paved roads cross washes through culverts; dirt tracks ford them. Cars are left out for now (the data put too many in).
- Roads come from the full OSM road download for the block, matched to the baked pieces way by way. Real control first: mapped stops and give ways win. Where nothing is mapped, signals go where three or more secondary-or-bigger arms meet; otherwise the straightest pair of the biggest roads runs through and the rest stop; equal roads crossing get an all-way stop. Junction nodes within 30 m of each other are one crossing.
- Untagged driveways are gravel (50%), dirt (30%) or asphalt (20%), chosen from the way id so it never changes; untagged residential roads are asphalt. A road whose surface turns out unpaved is repainted as dirt in the movement grid.
- Signals are dark: the power is out. Road paint and sign faces are clean but grimy; wear beyond that is for the decay pass.

## Interfaces

- Sector file format (see `bake.js`): `H` (153 × 153 heights in cm, base64 Int16, one extra sample each side), `nav` (kind and speed bytes, 300 × 300), roads (clipped pieces), water, areas, beds, lakes, pools, buildings, walls, plants `[type,x,y,z,sx,sy,sz,rx,ry]`, culverts, pois. `index.json` carries bridges, camps and the 5 km landscape.
- Runtime functions combat and the zoom page rely on: `heightAt`, `cellOf`, `kindG`, `nodeSpeed`, `findPath`, `deckAt`, `yOf`, sector build and drop hooks. Keep them or coordinate with `combat.md`.
- Road pass additions to the sector files (all optional; the runtime draws plain roads without them): per road piece `id` (OSM way), `lanes`, `lf`/`lb` (lanes each way), `ms` (mph), `turn`, `surf`, `added` (from the road pass); `rk` with `junctions` `[x,z,box?,paintGap,hull]`, `signs` `{k,x,z,y,…}`, `signals` `{x,z,y,L,h,n}`, `bars`, `walks`, `arrows`, `medians`, `gates`, `grids` and `undo`. `SectorCore.roadSection(road)` gives the cross-section both sides use. Sign posts and signal poles are not yet cover or line-of-sight blockers for `combat.md`.
- Coordinates: block frame centred on the block centre; `tools/zoom/glue-pre.js` converts to the region frame.

## Known gaps

- Single build steps over 100 ms (ground texture, plant instancing): split them or build in a worker.
- Ring sectors use full terrain (151 × 151); use coarser terrain and texture in the ring, sharper texture in the centre.
- Only one block baked; bake the whole corridor and stream across block edges.
- Building heights and roofs are guesses; no interiors; no doors or windows except shop glass.
- Anthem's OSM bridges overlap and clutter the area under West Anthem Way.
- Context terrain sits 14 m low inside the block to stay hidden; unloaded parts of the block look sunken from far away.
- Time of day and lighting are fixed in the streaming page.
- Cars: bring back a few, placed with intent (abandoned on roads, in drives), not from every parking lot.
- Roads: no traffic signals are mapped in the block, so the ones there are inferred; the real I-17 interchange is stop-controlled and stays so. `real-sectors.html` still has its old plain roads. The region download lacks driveways, footpaths and full road tags everywhere else: fetch them per block with `tools/osm/roadfetch.sh` before baking more blocks. Rock cuts are painted into the 0.6 m ground texture, so they are soft up close.

## First tasks

1. Split the long build steps (target under 30 ms each) and measure in a real browser.
2. Ring level of detail for terrain and textures.
3. Bake more blocks along the corridor; stream between blocks.
4. Building detail: roof types and facades from footprint and use. Doors, windows and what is inside belong to `interiors.md`; agree the hook that cuts their openings into your shells.

## Out of scope

Combat rules (`combat.md`), the region map (`strategy-map.md`), figures (`models.md`), building interiors (`interiors.md`).
