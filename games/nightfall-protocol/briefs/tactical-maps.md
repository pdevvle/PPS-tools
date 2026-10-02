# Brief: tactical maps

Read `00-foundation.md` first.

## Goal

The real ground at walking scale, everywhere in the region: baked offline from OpenStreetMap and elevation, streamed around the squad without hitches, with common-sense terrain, water, roads, bridges and buildings.

## Where it stands

- Pipeline: `tools/osm/fetch.sh`, `regionfetch.sh` (region download in 8 tiles; 7 are in, the south-east one keeps failing), `prep.py` (single sectors), `prep_block.py` (a block of sectors), `tools/stream/bake.js` with `sector-core.js` (shaping and placement shared by the bake and the browser), `tools/stream/stream-main.js` (streaming runtime). See `tools/stream/README.md` and `tools/osm/README.md`.
- `mockups/real-sectors.html`: two hand-built sectors (Anthem, New River) with the most visual detail: washes that run downhill, a flat-level lake basin, pools, culverts, bridges with an undercroft, a movement cost overlay, swim gear.
- `mockups/streaming/`: the New River block (5 × 5 sectors) baked and streamed 3 × 3 around the squad; centre sector with ink and full plants, ring lighter; paths across edges.
- Measured (software rendering): 45–80 ms to build a sector, longest single step 115–180 ms, about 40 ms to move the centre, 3 × 3 window about 360 draw calls and 2.2 M triangles, about 175 KB per sector compressed.

## Decisions (keep)

- Shape a whole block at once so sector edges match; ship per-sector files; build meshes in the browser a step at a time.
- 2 m movement grid with terrain speeds (foundation), a deck layer per bridge, water closed without swim gear.
- Bridges from OSM bridge tags: dig under the deck for headroom first, raise the deck and ramp the approaches for the rest. Washes over 3.4 m plus deck depth (an undercroft people can walk in); roads 5.3 m.
- Paved roads cross washes through culverts; dirt tracks ford them. Cars are left out for now (the data put too many in).

## Interfaces

- Sector file format (see `bake.js`): `H` (153 × 153 heights in cm, base64 Int16, one extra sample each side), `nav` (kind and speed bytes, 300 × 300), roads (clipped pieces), water, areas, beds, lakes, pools, buildings, walls, plants `[type,x,y,z,sx,sy,sz,rx,ry]`, culverts, pois. `index.json` carries bridges, camps and the 5 km landscape.
- Runtime functions combat and the zoom page rely on: `heightAt`, `cellOf`, `kindG`, `nodeSpeed`, `findPath`, `deckAt`, `yOf`, sector build and drop hooks. Keep them or coordinate with `combat.md`.
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

## First tasks

1. Split the long build steps (target under 30 ms each) and measure in a real browser.
2. Ring level of detail for terrain and textures.
3. Bake more blocks along the corridor; stream between blocks.
4. Building detail: doors, windows, roof types from footprint and use; enterable shells for shops (needed by combat and loot).

## Out of scope

Combat rules (`combat.md`), the region map (`strategy-map.md`), figures (`models.md`).
