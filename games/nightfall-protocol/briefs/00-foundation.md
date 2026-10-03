# Nightfall: foundation (general formula and values)

Owned by the home conversation. Topic conversations follow this; propose changes in PR descriptions.

## The game

An XCOM 2-inspired survival tactics game set in real places. The pilot region is the I-17 corridor north of Phoenix, Arizona: Desert Hills and Anthem north past New River towards Black Canyon City, about 18 by 32 km. A small group of survivors runs a home base and sends squads out.

Three layers compete for the player's attention:

1. **Logistic** (RimWorld-like): the base, its people, their jobs and what they make and use. See `building.md`.
2. **Strategic**: the region map. Squads travel real roads, time passes, knowledge of places fades. See `strategy-map.md`.
3. **Tactical**: the real ground at walking scale. Exploration is real time; contact folds into turn-based combat (XCOM-style) on the same ground. Whoever sees the other first gets the first strike, which gives a free shot. See `tactical-maps.md` and `combat.md`.

The world is hybrid: a sector map you plan on, and real-time exploration that drops into turns. You move between layers by zooming: all the way in on the map goes tactical at that spot; all the way out goes back to the map (`mockups/streaming/zoom.html`).

## Real places

- Maps come from OpenStreetMap (Overpass API) and elevation from Terrain Tiles on AWS (`s3.amazonaws.com/elevation-tiles-prod/terrarium`). Anything that shows map data credits "© OpenStreetMap contributors, ODbL"; derived data files are ODbL too.
- Download once and keep it; the public Overpass servers drop large queries and have usage limits. Tiles of the region are fetched in pieces with retries (`tools/osm/regionfetch.sh`).
- Common sense wins over raw data: water runs downhill and lies flat, roads cross washes on bridges or culverts, bridges have headroom, buildings sit on level pads.

## Art direction

- **Characters: inked toon.** Procedural faces and bodies from a seed (about 30 face values and 14 body values, heritage profiles that skew features). No hair or clothing in the base figure; both are procedural layers on top.
- **The ink stroke shows a character's state**: calm `#1d1814`, selected `#e0a526`, overwatch `#2f9fc4`, concealed `#5b6fa8`, wounded `#c23b2e`, panicked `#9b4fc4`. Raiders currently use a dark red stroke `#6e1a10`.
- **Props: ink faceted**: flat-shaded low-poly planes, a screen-constant outline, inked creases. Desert palette: sand `#cdb48c`, stucco and tile roofs, palo verde `#a7b85a`, saguaro `#5f7d3f`.
- Interface: dark frame (`#1b1c1e`), IBM Plex Sans Condensed and IBM Plex Mono, gold accent `#e0a526`.

## Units and scales

- 1 unit = 1 metre. x east, z south, y up.
- **Sector**: 600 m square. Region grid 30 × 53 sectors. A tactical **block** is 5 × 5 sectors (3 km), baked offline.
- Terrain: 4 m height grid in sectors, 100 m on the region map (shown at 1.6× vertical exaggeration).
- **Movement grid**: 2 m cells over the ground, plus a walkable layer on each bridge deck.
- Walking speed 5 km/h on asphalt. Multipliers: paved lot 1.0, footpath 0.95, dirt road 0.86, yard 0.8, open desert 0.72, sand wash 0.58; brush multiplies down to 0.42; slopes over 4° slow by (slope − 4)/30 down to 0.28; over 36° impassable. Water is closed without swim gear; with it, 0.2 (swimming).
- **Region travel**: paved 5 km/h, dirt 4 km/h, open desert 2.5 km/h, plus one hour per 300 m climbed. Water use 0.5 L per person per hour, doubled from 10:00 to 18:00.
- **Clock**: at 1×, 10 game minutes pass per real second on the map; 4× and pause.
- **Knowledge** of a sector: unknown, rumoured, scouted, current. Scouted goes stale after 3 days. Lookouts reveal 1 to 3 sectors around them, more from high ground.
- **Loot categories**: food, medicine, tools, fuel, gear, water, shelter, goods (derived from what a place really is).

## Time: two clocks

- **World clock** (sun, weather, travel, water, food, sleep): at 1× map speed 10 game minutes pass per real second, so one real hour is 25 game days. 4× fast-forward on the map; tactical exploration and fights run at their own pace and advance the world clock by the time they really take in the world.
- **Life clock** (ageing, pregnancy, growing up, skills that build over years): **one year of life per real hour of play at 1×**, which is 14.6 life days per game day. It is tied to the world clock, so fast-forwarded travel and long fights advance it too; that is what keeps an hour-per-year pace from feeling glacial.
- Rough consequences at 1×: pregnancy about 45 minutes of play (18 game days); a child becomes an adult (16 years) in about 16 hours; a 25-year-old reaches old age (60) in about 35 hours. A 40–80 hour campaign spans two generations.
- Needs (water, food, sleep) run on the world clock; age and lifespan run on the life clock. Systems state which clock each rate uses.

## Simulation rules

- **Tiers.** The player's settlement runs at full detail: every survivor simulated individually (first draft target 15–30 people). Other settlements, raider groups and traders in the region are aggregates (population, stocks, attitude) and become individuals only when visited or fought. The tactical window is the only place with per-frame simulation.
- **Cadence.** Needs drain at continuous rates settled each game hour; jobs are chosen when a task ends (utility AI); social interactions every few game hours; stores, spoilage and prices daily; demographics and civics daily to seasonal. Continuous rates let any stretch of time be fast-forwarded in one step.
- **Control.** Indirect for the settlement: the player sets priorities, roles and rules, and survivors decide what to do (RimWorld-style). Direct for squads in the field and in combat.
- **Portable logic.** Simulation is plain functions over plain data, with no rendering inside, deterministic from seeds, runnable in a worker and later in WebAssembly or native code. Saves record the state and what changed from the generated world, not snapshots of it.
- **Region.** A few other settlements in the corridor (abstract until visited) plus travelling traders; first draft can start with traders only.

## Combat values (from the demonstration; combat owns tuning)

Two actions per soldier; an action moves up to 12 "effective metres" (distance divided by the terrain multiplier). Shooting ends the turn. Aim: squad 72, raiders 60. Cover −20 half, −40 full; hunker adds another −20 when in cover; +15 from more than 2 m higher; −1.5 per metre beyond 24 m (to −40); +10 under 8 m; overwatch reaction −15; first-strike free shot +10 against targets without cover. Crit 10%, 40% when flanked. Damage 3–5, +2 on a crit. HP: squad 6, raider 4, raider boss 6. Raiders see 16 m in a 130° cone, 5 m all round; the squad spots at 30 m with line of sight.

## Tech and conventions

- three.js r128 (UMD from cdnjs). One self-contained HTML file per mockup; no build step in the browser.
- Published Artifacts are HTML fragments starting with `<title>` (no doctype); repo copies are wrapped in a doctype and live under `mockups/`. External scripts only from cdnjs, jsDelivr or unpkg; fonts from Google Fonts. Artifacts serve JSON but not binary files.
- Tests: Playwright with Chromium at `/opt/pw-browsers/chromium`, flags `--use-angle=swiftshader --enable-unsafe-swiftshader`, routing `**/three.min.js` to `node_modules/three`. Software rendering is slow (about 1 s a frame for a full sector), so judge frame rate in a real browser.
- Repo: `games/nightfall-protocol/` — `index.html` (the original XCOM-like game), `mockups/`, `tools/osm` (data pipeline), `tools/stream` (bake and streaming), `tools/zoom` (zoom page and combat), `data/` (ODbL data), `briefs/`.
- Commit each change with a clear message; push to your branch; PR against `claude/quickbooks-book-categorizer-Q85ha`.

## Design documents

- World map design doc (Claude Docs): https://claude.ai/code/artifact/eaeabb9c-a2cd-45d7-aafb-821d7407a865 — fixed region, stylised 3D map, several squads at once, zoom levels, data shapes, build order.
- Clothing schema doc (Claude Docs, id `7257d5ff-…`): the layer model for clothing on the procedural figures.

## Published prototypes

- Figure study: https://claude.ai/artifact/3vqVa5cSPH7qrn3wRiNAxK
- Procedural motion: https://claude.ai/artifact/AJZoX7SFq7axAaQ1TMUfJH
- Real sectors (Anthem, New River): https://claude.ai/artifact/Xu8MgNRtqQov4F2yoBYyr5
- Region map: https://claude.ai/artifact/Afixa1XUKwbP94ZYBYha46
- Streaming: https://claude.ai/artifact/HeGShXFT4CJYnEXUGXd3UK
- Corridor zoom with the combat demo: https://claude.ai/artifact/JH6akGR41Kop5w4F8xmM3a
- Original game: https://claude.ai/artifact/7MGEEBBNtdEULS7he633y3
