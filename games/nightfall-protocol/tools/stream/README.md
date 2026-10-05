# Sector streaming

The tactical layer streams real terrain a 600 m sector at a time. This is the groundwork.

1. `../osm/corridorfetch.sh` downloads everything the bake needs for the corridor (raw files in `tools/osm/raw/`, kept out of git), and `../osm/prep_block.py corridor 5 10 0 -1500` cuts a rectangle of sectors from it: 5 across, 10 down, in the frame centred on New River (so the New River block is rows 5–9 and the block north of it rows 0–4). Features in frame metres, a 4 m height grid with a margin, and the landscape 5 km round it. The whole corridor is shaped at once, so roads, washes and bridges match across the join between the two blocks.
2. `bake.js` runs `sector-core.js` over the whole block at once, so washes, graded roads, bridge ramps and building pads carry across sector edges. It then writes one JSON file per sector: heights (153 × 153 samples, one extra on each side for shading), the 2 m movement grid, plants, walls, clipped roads, water, buildings, culverts, pools, lakes and loot sites. Bridges, the camps under them and the landscape go into `index.json`, because a deck can cross a sector edge.
3. `roads-bake.js` is a pass over the baked sector files that brings in the full road data (`../../data/roads/`, fetched with `../osm/roadfetch.sh`). It matches each road piece to its OSM way and adds its lanes, speed limit, turn lanes and surface; adds the driveways, tracks and paths the region download left out, painting them into the movement grid and clearing plants and boulders from them; and works out the roadside, written to each sector as `rk`:
   - junctions: close OSM junction nodes are merged into one crossing, outlined as a paved box;
   - control: stop and give-way signs where OSM maps them; signals inferred where three or more secondary-or-bigger arms meet (none are mapped here); otherwise the straightest pair of the biggest roads runs through and the rest stop, or an all-way stop where equal roads cross. Stop bars, crosswalks at signals, turn arrows from `turn:lanes`, do-not-enter signs at exit ramp ends;
   - signs: speed limits after junctions and where OSM maps them, the exit 232 gore and advance guide signs from the junction and destination tags, I-17 route shields after the on-ramps and trailblazers at their entrances, street-name blades on every stop sign;
   - the cable barrier down the freeway median, ranch gates and cattle guards.
   - power: the real 69 kV lines and their substation from `osm_power_*.json` (poles on every vertex, crossarms square to the line, guy wires at ends and corners); inferred 12 kV distribution on wooden poles about 50 m apart along the bigger roads, a transformer and a service drop for each house within 45 m;
   - street lights (all dark): cobra heads on the utility pole nearest a bigger crossing, a luminaire on every signal pole, the state's davit poles at the I-17 ramp ends, shoebox lights round parking lots;
   - abandoned cars (`rk.cars`, `[x,z,yaw,type,colour,flags,seed]`): queued at the dead signals, waiting at the odd stop sign, on the freeway shoulders and lanes with the occasional crash, pulled over or left in the lane elsewhere, burnt out off the tracks, parked at the house end of driveways and in lots. Each blocks its cells as a new movement kind, `Wreck`, which combat counts as full cover.
   - bridge ends: the bake marked 'no headroom' round each deck's centreline past its ends too, which closed the ground the deck joins; the pass reopens it (approach road as asphalt, the rest as ground), so every deck inside the block can be walked.
   - solid plants: saguaros, palo verde trunks, shrubs and boulders close the cells they stand in, and their neighbours where the plant reaches, as a movement kind of their own (`Plant or boulder`); reeds don't.
   Every sign and pole is nudged off the pavement. The pass records what it changed (`rk.undo`), so it can be rerun on its own output.
4. `stream-main.js` is the page. It keeps the 3 × 3 sectors around the squad loaded and builds each one a step at a time between frames, under an 8 ms budget per frame. The centre sector gets ink outlines, creases and every plant; the ring gets lighter plants and no ink. Sectors two away are dropped and their geometry, textures and movement cells released. Paths run on one block-wide grid that sectors fill in as they load, plus a deck layer for each bridge.

`road-kit.js` draws the roads from that: procedural textures for asphalt lanes (wheel paths, the oil line, cracks, sealant, patches; dark rubberised asphalt on the freeway and arterials, bleached chip seal on local roads), concrete panels, gravel, graded dirt (ruts, crown, washboard, grader berms) and sand, laid on the cross-section from `SectorCore.roadSection` with gravel verges; paint (edge and lane lines, double yellow, dashed passing lines that turn solid near junctions, freeway rumble strips); and the roadside, built from code as ink-faceted props: stop, yield, speed, do-not-enter, exit, guide and route signs whose faces come from one canvas atlas, mast-arm signals (dark, there is no power), delineators, the cable barrier, gates, cattle guards, and rock exposed where a road was cut into a hill. Roads sample the terrain mesh's own triangles so the ground never shows through them.

Wear and decay are generated in the browser from fixed seeds, so they are the same on every visit: potholes in the wheel paths (more on local roads than the freeway), alligator cracking, sand drifts blown in from the west-south-west edge where a road crosses open desert and sand fans where washes run over it, and weeds in the potholes, the cracks, the centre seam and along the pavement edge.

The page runs a clock (pause, 1× and 4×, or Space) like the map: exploring is real time, and on the zoom page the map catches up by the game seconds spent on the ground. Clicking a square in the sector overview sets the squad down there.

## The desert: washes, rock and plants

**Drainage.** The map knows only a dozen washes; the ground has hundreds. The bake routes water over the 4 m height grid (each cell drains to its steepest neighbour, flow accumulated from the top down), and wherever 2.4 ha or more drains through a cell outside the mapped washes it cuts a wash, wider and deeper as the area grows (1.2–4 m half-width, 0.3–1.2 m deep). About 140 come out of the corridor. **New River** gets a braided bed: four low-flow channels wandering across the mapped sand and scree between bars, steeper cut banks, a strand line of flood debris along the edge.

**Plants and rock by habitat** (`SectorCore.PLANTS` is the table: 26 kinds with movement reach, cover, brush drag and ring visibility). Every 4.2 m the bake reads the ground and picks a habitat, then a species from that habitat's community:

| Habitat | Rule | Community |
|---|---|---|
| River bed | inside the mapped bed | cobbles, desert broom, grass, flood wood, boulders; bare damp sand in the braids |
| Wash channel | inside any wash | broom, cobbles, grass, the odd catclaw |
| Wash bank | within 4 m + 1.6 × half-width | xeroriparian: blue palo verde, mesquite, ironwood, catclaw, wolfberry, jojoba, a dead tree now and then |
| Cliff | slope over 34° | rock faces (slabs tilted into the slope), boulders, agave, ocotillo, brittlebush, barrel cactus |
| Outcrop | ridge crests (convex), mapped bare rock, or rocky patches on slopes over 22° | granite tors in piles, ocotillo, agave, teddy bear cholla, saguaro |
| South slope | over 9°, facing south | saguaro, foothill palo verde, ocotillo, brittlebush, teddy bear cholla |
| North slope | over 9°, facing north | jojoba, palo verde, brittlebush, grass, fewer saguaros |
| Bajada | gentle ground | creosote and white bursage, buckhorn cholla, prickly pear, saguaro |
| Desert pavement | flat, sparse patches | creosote, bursage, stones |
| Roadside | within 6 m of a road | desert broom, brittlebush, grass |
| Yard | mapped residential | wolfberry, mesquite, palo verde, agave, prickly pear |

Elevation shifts the mix (creosote and bursage thin above 760 m, grass and jojoba come in, saguaros leave cold north slopes), mapped grassland, scrub and bare rock nudge it, and slow noise gives patches. On the ground, slopes over 20° show their rock, darker on cliffs with joints and ledges across the slope, lighter on rounded ridges; washes are painted with cut-bank bands, sandy beds and gravel down the thalweg. `flora-kit.js` builds the plants (instanced, several parts each) and paints that ground.

`car-kit.js` builds the cars: sedans, hatchbacks, SUVs, pickups and vans lofted along their length from side profiles, with wheel arches, glass, pillars, door seams and handles, mirrors, bumpers, grilles, lamps and plates, tyres and rims, roof rails, pickup beds with cargo; and their state from the flags: burnt out (charred, rusting, on bare rims), flat tyres, a wheel gone with the corner on a block, bonnet up over the engine bay, broken glass, the driver's door hanging open, dust and rust.

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
