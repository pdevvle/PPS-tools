# Sector streaming

The tactical layer streams real terrain a 600 m sector at a time. This is the groundwork.

1. `../osm/prep_block.py` cuts a block of sectors (5 × 5 around New River by default) out of the region download: OSM features in block metres, a 4 m height grid with a margin, and the landscape 5 km around.
2. `bake.js` runs `sector-core.js` over the whole block at once, so washes, graded roads, bridge ramps and building pads carry across sector edges. It then writes one JSON file per sector: heights (153 × 153 samples, one extra on each side for shading), the 2 m movement grid, plants, walls, clipped roads, water, buildings, culverts, pools, lakes and loot sites. Bridges, the camps under them and the landscape go into `index.json`, because a deck can cross a sector edge.
3. `stream-main.js` is the page. It keeps the 3 × 3 sectors around the squad loaded and builds each one a step at a time between frames, under an 8 ms budget per frame. The centre sector gets ink outlines, creases and every plant; the ring gets lighter plants and no ink. Sectors two away are dropped and their geometry, textures and movement cells released. Paths run on one block-wide grid that sectors fill in as they load, plus a deck layer for each bridge.

`sector-core.js` has no rendering code, so the same file runs in Node for the bake and in the browser (and could run in a worker).

## Measured (headless Chromium, software rendering, so frame times are not representative)

- Building one sector from its file: 45–80 ms, longest single step about 115–180 ms (the ground texture or the plant instancing).
- Moving the centre (ink and plant detail swap): about 40 ms.
- 3 × 3 window: about 360 draw calls and 2.2 M triangles; JS heap about 60 MB; geometry and texture counts stay flat as sectors are dropped and loaded.
- Files: about 175 KB per sector compressed (550 KB raw JSON); the bake takes about a minute for 25 sectors.

## Next

- Split the ground-texture and plant steps so no single step tops about 30 ms, or move mesh building into a worker.
- Coarser terrain and texture for the ring; a 2048 texture for the centre.
- Bake more of the region (the full I-17 corridor download is in) and stream between blocks.
