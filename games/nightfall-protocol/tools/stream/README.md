# Sector streaming

The tactical layer streams real terrain a 600 m sector at a time. This is the groundwork.

1. `../osm/prep_block.py` cuts a block of sectors (5 × 5 around New River by default) out of the region download: OSM features in block metres, a 4 m height grid with a margin, and the landscape 5 km around.
2. `bake.js` runs `sector-core.js` over the whole block at once, so washes, graded roads, bridge ramps and building pads carry across sector edges. It then writes one JSON file per sector: heights (153 × 153 samples, one extra on each side for shading), the 2 m movement grid, plants, walls, clipped roads, water, buildings, culverts, pools, lakes and loot sites. Bridges, the camps under them and the landscape go into `index.json`, because a deck can cross a sector edge.
3. `roads-bake.js` is a pass over the baked sector files that brings in the full road data (`../../data/roads/`, fetched with `../osm/roadfetch.sh`). It matches each road piece to its OSM way and adds its lanes, speed limit, turn lanes and surface; adds the driveways, tracks and paths the region download left out, painting them into the movement grid and clearing plants and boulders from them; and works out the roadside, written to each sector as `rk`:
   - junctions: close OSM junction nodes are merged into one crossing, outlined as a paved box;
   - control: stop and give-way signs where OSM maps them; signals inferred where three or more secondary-or-bigger arms meet (none are mapped here); otherwise the straightest pair of the biggest roads runs through and the rest stop, or an all-way stop where equal roads cross. Stop bars, crosswalks at signals, turn arrows from `turn:lanes`, do-not-enter signs at exit ramp ends;
   - signs: speed limits after junctions and where OSM maps them, the exit 232 gore and advance guide signs from the junction and destination tags, I-17 route shields after the on-ramps and trailblazers at their entrances, street-name blades on every stop sign;
   - the cable barrier down the freeway median, ranch gates and cattle guards.
   Every sign and pole is nudged off the pavement. The pass records what it changed (`rk.undo`), so it can be rerun on its own output.
4. `stream-main.js` is the page. It keeps the 3 × 3 sectors around the squad loaded and builds each one a step at a time between frames, under an 8 ms budget per frame. The centre sector gets ink outlines, creases and every plant; the ring gets lighter plants and no ink. Sectors two away are dropped and their geometry, textures and movement cells released. Paths run on one block-wide grid that sectors fill in as they load, plus a deck layer for each bridge.

`road-kit.js` draws the roads from that: procedural textures for asphalt lanes (wheel paths, the oil line, cracks, sealant, patches; dark rubberised asphalt on the freeway and arterials, bleached chip seal on local roads), concrete panels, gravel, graded dirt (ruts, crown, washboard, grader berms) and sand, laid on the cross-section from `SectorCore.roadSection` with gravel verges; paint (edge and lane lines, double yellow, dashed passing lines that turn solid near junctions, freeway rumble strips); and the roadside, built from code as ink-faceted props: stop, yield, speed, do-not-enter, exit, guide and route signs whose faces come from one canvas atlas, mast-arm signals (dark, there is no power), delineators, the cable barrier, gates, cattle guards, and rock exposed where a road was cut into a hill. Roads sample the terrain mesh's own triangles so the ground never shows through them.

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
