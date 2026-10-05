# Brief: the tactical ground inside the strategy map

From the tactical-maps conversation to the strategy-map conversation. Read `00-foundation.md`, `strategy-map.md` and `tactical-maps.md` first. This brief says what the tactical ground now offers, what the map should do with it, and which interfaces to agree. Where a task is the tactical side's, it says so; the tactical-maps conversation will do those.

## What the tactical ground is now

- **A corridor, not a block.** New River and the block north of it, baked together: 5 × 10 sectors of 600 m (3 by 6 km) in the frame centred on New River (33.918 N, 112.13855 W). `mockups/streaming/block/index.json` gives `nx`, `nz`, `x0`, `z0` (the north-west corner, frame metres), `sector`, `navStep`, `bridges`, `camps`, `context`, and one entry per sector. More blocks will extend the same rectangle; the frame never moves.
- **`NF.BLOCK`** in `tools/zoom/glue-pre.js` is the corridor's rectangle (`x0:-1500, z0:-4500, x1:1500, z1:1500`). `NF.inBlock`, `NF.rect`, `NF.regionToBlock` and `NF.blockToRegion` all use it, so diving already works anywhere in the gold outline.
- **Each sector file** carries, besides terrain and the 2 m movement grid:
  - buildings with footprint, type, name, loot category and `what`, and a `house` flag; `pois` (named shops and services);
  - roads with OSM way id, lanes, speed limit and surface; driveways and tracks;
  - `rk`: junctions, signs, signals, power poles and lines, street lights, and **abandoned cars** (`[x,z,yaw,type,colour,flags,seed]`, about 190 in the corridor; flags say burnt, flat, bonnet up and so on);
  - plants and rock by **habitat** (`SectorCore.PLANTS`, 26 kinds), about 140 washes derived from drainage, New River's braided bed.
- **Movement kinds** (`SectorCore.NAVKIND`) include `car` (Wreck) and `plant` (Plant or boulder); both block movement, and combat counts cover from them.
- **Tactical clock**: pause, 1× and 4× (Space). `NF.tacEnter` starts it at `Campaign.state.minutes`; `NF.tacSeconds()` returns game seconds spent on the ground (4× counts four times), and `glue-post.js` passes that to `__region.back()` instead of real time.
- **Hooks the map already uses**: `NF.tacEnter(x,z,squad)`, `NF.tacState()` → `{x,z,squad:{x,z,index,people}}`, `NF.tacSeconds()`, `NF.tacBusy()`, `NF.tacResult()` (combat's).

## Tasks for the strategy map

1. **Read the baked area from data, not a constant.** Replace the literal `BLOCK` in `glue-pre.js` with the extent from the block index (`x0`, `z0`, `nx`, `nz`, `sector`), so a new bake needs no code change. When there is more than one baked area, take a list. Also update the tip in `region-main.js` (`dive`): it still says "the gold New River block".
2. **Use the tactical summaries for the sectors inside the corridor.** The tactical side will add a `summary` to each entry of `index.sectors` (task A below). Inside the corridor, prefer it to the realm's estimates:
   - `speed`: mean walking speed over the sector's 2 m grid, for off-road travel times in `campaign.js`;
   - `buildings`, `houses`, `cars`: real counts, for the sector panel and loot estimates;
   - `cover`: share of cells giving half or full cover, and `habitats` (share of bajada, slope, outcrop, cliff, bank, bed, yard): describe the ground ("rocky hills, saguaro slopes", "creosote flats") and feed raider camp choice;
   - `water`: whether a wash or the river crosses it.
3. **Knowledge from walking the ground.** While a squad explores, every sector it enters becomes *current*, and sectors it can see from high ground become *scouted*. The tactical side will report them in `NF.tacState().seen` (task B). On `back()`, mark them in `Campaign.state.know` with the game time of the visit.
4. **Sites and buildings are the same things.** A region site inside the corridor should point at the tactical building or POI it stands for (nearest building with the same `what`, or within 25 m). Then:
   - searching a site on the map and scavenging it on the ground use the same stock;
   - what the ground reports taken (task C) depletes the region site;
   - the map can show sites the region data lacks, from tactical buildings flagged `house` or with a `loot` category.
5. **Encounters on real ground.** `NF.encounter.enemy.pos` and `squad.pos` are in the region frame: convert with `NF.regionToBlock` and hand them over. The tactical side will set the raiders down on the nearest walkable cell and choose cover from the habitat (task D). Keep `light` and `tempC` in the encounter: the tactical side will use them for lighting and visibility (task E).
6. **Remember what changed on the ground.** Add `Campaign.state.ground`, keyed by sector `"c,r"`, holding a small record of changes over the generated ground: sites emptied, containers opened, cars searched, doors forced (interiors), bodies. The tactical side reads it on entering and writes it on leaving (task C). It saves with the rest of the campaign.
7. **Squads leaving the ground.** A squad that walks off the corridor's edge should come back to the map at that edge. Clamp on `back()` and, when a squad stands within 30 m of the edge on the ground, offer to return to the map.
8. **Several squads on the ground.** For now one squad goes down at a time. Note which other squads stand inside the corridor, so a later step can bring two squads together on the same ground.

## Tasks for the tactical side (the tactical-maps conversation will do these)

- **A. Sector summaries** in `index.json` from the road pass: `speed`, `buildings`, `houses`, `cars`, `cover`, `habitats`, `water`.
- **B. `seen`** in `NF.tacState()`: sectors entered, and sectors in view from high ground (a coarse sight check on the region's 100 m terrain).
- **C. Ground changes**: read `Campaign.state.ground` on entering, apply it (empty sites, searched cars), and return changes and items taken in `NF.tacState()`.
- **D. Encounter placement**: raiders on walkable cells near `enemy.pos`, facing the squad, in cover chosen from the habitat and the plant table; their camp where the map says they camp.
- **E. Time of day**: lighting, sky and visibility from `light` and the campaign clock, ticking with the tactical clock; night shortens spotting ranges.
- **F. Frame rate**: the dense plants since the habitat pass cost frames in places. Coarser plant stand-ins in the ring sectors, fewer small plants at a distance, and splitting the long build steps. This doesn't change any interface.
- **G. More blocks**: south to Anthem and north toward Black Canyon City, extending the same rectangle, with the full OSM download per block (`tools/osm/corridorfetch.sh`).

## Interfaces to agree

```
// index.json, per sector (tactical writes, map reads)
{ c, r, bytes, gz, b, plants,
  summary:{ speed /*0..1 of asphalt*/, buildings, houses, cars, cover /*0..1*/,
            habitats:{bajada,slope,slopeN,slopeS,outcrop,cliff,bank,bed,yard,roadside,pavement}, water:bool } }

// NF.tacEnter(x, z, squad, opts)   opts: { minutes, light, tempC, encounter, ground }
// NF.tacState() → { x, z, squad:{x,z,index,people},
//                   seen:[{c,r,level:'current'|'scouted'}],      // tactical sector indices
//                   ground:{ "c,r": [ {k:'site',id,taken:{food:2,…}}, {k:'car',i}, … ] } }
```

Sector indices here are the corridor's (`c` across, `r` down from `x0,z0`); `NF` should offer `blockSectorToRegion(c,r)` so the map never does the arithmetic itself.

## Decisions to make together

- How a region sector (600 m, realm grid) maps to tactical sectors: the grids are both 600 m but their origins differ. Either align the realm grid to the corridor or convert by position everywhere. Converting by position is simpler and the recommendation.
- Whether ground changes expire (other scavengers, `1.5% a day` picking over), the same way region sites do.
- What the map shows inside the corridor: tactical buildings and cars as dots when zoomed in, or keep the stylised map.

## Out of scope here

Combat rules (`combat.md`), interiors (`interiors.md`), the base (`building.md`).
