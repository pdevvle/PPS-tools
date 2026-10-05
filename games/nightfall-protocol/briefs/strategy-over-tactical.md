# Brief: the strategy map over the tactical ground

From the strategy-map conversation to the tactical-maps conversation. It is the inverse of `strategy-tactical-integration.md`: that brief brings the tactical ground into the map; this one carries the map onto the ground. Read `00-foundation.md`, `strategy-map.md`, `tactical-maps.md` and `strategy-tactical-integration.md` first. Where a task is the strategy side's, it says so; the strategy-map conversation will do those.

## State (built in the tactical-maps conversation)

All of it runs on the zoom page only; the standalone streaming page is unchanged (task 9).

- **S1–S5** are in `tools/region/region-main.js` as `__region.paintKnowledge`, `groundTexture`, `tick`, `takePose` and `pose`; `Campaign.tick(minutes,{except})` and `Campaign.searchNow(i,site)` are new in `campaign.js` (tested in `test.js`). The map's dive records its camera as `NF.mapPose`, and `NF.exitTactical` hands the ground's pose to `takePose` (S4, done with poses on both sides rather than a `NF.camHandoff` function).
- **Tasks 1–8** are a `LIVE` section in `tools/zoom/stream-z.js`:
  1. the horizon is the realm: a 100 m mesh 10 km round the corridor and an 800 m mesh over the whole realm, both from `Campaign.elevAt` and draped with `groundTexture`; past loaded sectors `heightAt` falls back to the same terrain;
  2. the map lens (Layers: *Map lens*): `paintKnowledge` plus a bold sector grid with sector names, on the near horizon and every loaded sector, fading in as the camera rises past 380 m;
  3. one clock: `__region.tick` runs every quarter second with the squad on the ground excluded; encounters open on the ground with a banner (fight it out, pull back, lie low) that pauses the clock; `NF.tacSeconds()` returns 0 once the clock has run live, so `back()` only charges fight turns;
  4. raider bands the squad can see stand on the ground as armed figures where the campaign has them, last sightings are labelled, and the other squads inside the corridor show as figures with their names;
  5. water is spent by `waterRate` and heat, thirst and darkness slow walking through `paceAt`, the clock shows temperature and water, and the sun, sky and fog follow `sunAt`;
  6. zooming out hands the pose to the map, zooming in starts the ground from the map's pose;
  7. a click past the loaded ground (on the horizon, or outside the corridor) routes with `Campaign.route`, draws the route on the ground, walks to the edge of the loaded ground and hands the rest to the map as a trip;
  8. the campaign's sites inside the loaded ground are labelled with what is left, and **Search** (within 45 m) calls `searchNow` and lets the hours pass.
- Not yet: a live encounter on the ground is answered by the banner, not fought in combat (combat still fights only its demonstration camp); raiders outside the loaded ground stay map markers.

## Goal

Standing on the tactical ground should feel like being inside the strategy map. The world goes on past the loaded sectors, the same campaign keeps running, and pulling the camera up turns the ground back into the map without a cut. Nothing the map knows should be lost on the way down, and nothing on the ground should contradict it.

## What the strategy map offers now

- **The realm.** `data/region/region_i17.json`, embedded as `REGION` in the zoom page. It is 100 miles square (270 × 269 sectors of 600 m) in the region frame centred on 33.945 N, 112.14 W.
  - Terrain at 400 m over the whole realm (`REGION.dem`), and at 100 m over the I-17 corridor (`REGION.demFine`), on one base height.
  - The travel graph, places and peaks, about 31,000 sites, land use, and the corridor's buildings.
  - `Campaign.hRaw(x,z)` samples the best terrain at any point; `Campaign.elevAt` adds the base.
- **The campaign** (`tools/region/campaign.js`, the global `Campaign` on the zoom page). It has no rendering code, and its state is `Campaign.state`:
  - `minutes`: the clock
  - `know[r][c]`: `{k: 0 unknown, 1 rumoured, 2 scouted, 3 current, seen}`
  - `squads`: `x, z, people, water, pack, trip, task`
  - `bands`: raiders, with `x, z, size, trip, seen`
  - `sites`: stock, visits
  - `enc`: an open encounter
  - `base.stock`
- **Rules to call rather than copy:**
  - `sunAt(min)` → `{daylight, phase, tempC, elev, arc}`
  - `tempAt(min,x,z)` and `heatOf(tempC)`
  - `waterRate(moving, heat)`, `paceAt`
  - `secAt`, `secCentre`
  - `stockOf`, `leftOf`, `canScavenge`, `scavenge`
  - `squadSight`, `bandSight`, `reveal`, `refreshCurrent`
  - `step(minutes)`, `resolve(choice, result)`, `route`
- **The region side of the zoom page** (`window.__region`): `back(gameSeconds, result)`, `placeSquad`, `advance(minutes)`, `focus`, `camT`, `squads`, `know`, `save`.
- **Frames.** `NF.regionToBlock` and `NF.blockToRegion` convert between the region frame and the corridor's block frame (centred on New River).

## Tasks for the tactical side (the tactical-maps conversation)

1. **The horizon is the realm.** Replace the block's own `context` grid (321 × 321 at 50 m, most of `index.json`) with the realm's terrain past the loaded sectors.
   - Sample it with `Campaign.hRaw` through `NF.blockToRegion`, or take `REGION.demFine` and `REGION.dem` directly. Build it as rings: 100 m near the corridor, 400 m beyond.
   - Drape the map's ground texture on it (task S2). The far land then matches the map exactly, and the world doesn't end at the corridor's edge.
   - Keep the landscape a little low inside loaded sectors, as now, so loaded ground always covers it.
2. **A map lens on the ground.** Add a toggle (and, later, an automatic fade as the camera rises; task 6) that drapes the strategy layer over the tactical terrain:
   - the 600 m sector grid
   - knowledge as the map shows it: unknown hatched, rumoured tinted, stale scouted greyed
   - the home sector, the selected sector, and squad routes
   Use the strategy side's painter (task S1) on a texture over the terrain, not new rules.
3. **One clock, one campaign.** While a squad is on the ground, let the campaign run live instead of catching up on return:
   - each frame, call `__region.tick(gameMinutes, {except: squadIndex})` (task S3) with the tactical clock's elapsed game time.
   - Other squads keep travelling, searching and drinking; raider bands roam and camp; and an encounter can open while you're down there. Show it in the tactical UI and let it be answered there.
   - The squad on the ground is driven by the tactical layer, not by its trip.
   - `NF.tacSeconds()` stays as the fallback when the page has no campaign (the standalone streaming page).
4. **The campaign's actors on the ground.**
   - **Raider bands** within sight of the squad (`Campaign.bandSight` / `squadSight` against the band's position) appear as figures at their converted positions, walking their `trip` on the nearest walkable cells. A band that isn't seen stays hidden. One that comes close opens an encounter through the campaign (`Campaign.step` does this), and combat takes over as `strategy-tactical-integration.md` task D describes.
   - **Other squads** standing in the corridor show as their figures. They're idle unless they have a trip, in which case they walk it.
   - **Last-seen markers** for bands (`band.seen`), as on the map, shown as a ghost or label where they were spotted.
5. **Heat, water and light from the campaign.**
   - Every second on the ground spends the squad's water at `waterRate(moving, heatOf(tempAt(minutes, x, z)))` times its people, and the HUD shows water and temperature.
   - Thirst slows walking like `paceAt` does on the map.
   - The sun, sky and visibility come from `sunAt` (as in `strategy-tactical-integration.md` task E), so the ground and the map agree on what time of day it is.
6. **Zoom out is the map.** Replace the fade with a camera handover:
   - As the tactical camera climbs past a set height, pass its pose to the map with `NF.camHandoff({x, z, y, yaw, pitch, dist})` (task S4) in the region frame. The map takes over from exactly that view.
   - Zooming in on the map hands the pose back the same way.
   - Use the lens (task 2) and the realm horizon (task 1) to cross-fade over the last stretch, so the switch hides inside the overlap: the map draws the same terrain and texture the tactical horizon already shows.
7. **Orders that reach past the loaded ground.** A move ordered to a point outside the loaded window (or outside the corridor) becomes a map order:
   - `Campaign.route` gives the way.
   - The squad walks the first part on the ground. When it reaches the edge of the loaded ground (or the corridor), hand back to the map with the trip already set (`strategy-tactical-integration.md` task 7 covers the edge).
   - Draw the route on the ground as the map draws it.
8. **Sites on the ground.** Region sites inside the loaded sectors show their campaign state through `leftOf(i)`: untouched, how much is left, or searched out. Searching one on the ground calls `Campaign.scavenge`, or uses its stock directly. This ties in with `strategy-tactical-integration.md` task 4, and that brief's mapping from sites to buildings holds.
9. **Without a campaign.** The streaming page (`mockups/streaming/index.html`) has no `Campaign`. Every task above must leave it working as it does now.

## Tasks for the strategy side (the strategy-map conversation will do these)

- **S1. Knowledge painter.** Expose `__region.paintKnowledge(ctx, toCanvas)`: it draws the sector grid, the knowledge tints and hatch, the home outline and routes onto any 2D canvas through a mapping from region metres to canvas pixels. The map's own overlay will use the same function.
- **S2. Ground texture for the horizon.** Expose `__region.groundTexture(extent, size)`: the realm's ground (elevation tint, land use, water, roads, hillshade) drawn over any extent in region metres, so the tactical horizon can use it.
- **S3. Live tick.** `__region.tick(minutes, {except})` steps the campaign (squads, bands, encounters, knowledge) without moving the excluded squad. It returns what changed: `{encounter, revealed, arrived, found}`. `back()` then only places the squad and settles the encounter, since no time is owed.
- **S4. Camera handover.** `NF.camHandoff(pose)` in both directions. The map accepts a pose in the region frame and starts its camera there (no snap). It also offers its own pose when it zooms past its closest distance, with the dive point and the squad, so the tactical camera can start where the map left off.
- **S5. Encounter answers from the ground.** `Campaign.resolve` already takes `avoid`, `hide`, `fought` and `auto`. When an encounter opens during a live tick, the strategy side won't show its own dialog while `NF.mode` is `'tactical'`. The ground answers it.

## Interfaces to agree

```
// strategy side (window.__region), for the tactical side
tick(minutes, {except}) → {encounter|null, revealed, arrived, found}
paintKnowledge(ctx, toCanvas)            // toCanvas(x, z) → [px, py], region metres to canvas pixels
groundTexture([x0, z0, x1, z1], size) → HTMLCanvasElement
// shared
NF.camHandoff({x, z, y, yaw, pitch, dist, from: 'map'|'ground'})   // region frame; y is metres above the terrain
// unchanged
Campaign.sunAt / tempAt / heatOf / waterRate / paceAt / squadSight / bandSight / stockOf / leftOf / scavenge / route
NF.regionToBlock / NF.blockToRegion
```

## Decisions to make together

- **The clock.** A live tick (task 3) replaces "catch up on return", with one clock for both layers. The rates stay as the foundation sets them: real time while exploring, 5 minutes per character turn in a fight. Recommended.
- **Where the horizon ends.** All 100 miles at 400 m is about 400 × 400 samples, cheap enough. Or stop at the fog distance.
- **The lens.** Off by default and faded in as the camera rises (recommended), or always visible at low strength.
- **Raiders outside the corridor.** When a band is walked onto ground that isn't baked, it stays a map marker until on-demand baking exists.

## Out of scope here

Baking ground on demand outside the corridor (open; see `strategy-map.md`), combat rules (`combat.md`), interiors (`interiors.md`).
