# Brief: building (the logistic layer)

Read `00-foundation.md` first.

## Goal

The base: the survivors' home where people live, work, build and use what the squads bring back. RimWorld-like management on real ground, feeding and fed by the strategic layer.

## Where it stands

One-page design done (see Decisions). What exists to build on:
- The home sector is near New River on the region map (`data/region/region_i17.json` `home`), inside the baked New River block, so the base can sit on the streamed tactical ground.
- Loot categories (food, medicine, tools, fuel, gear, water, shelter, goods) and water use per person per hour (foundation).
- The 2 m movement grid (walls and buildings block, terrain sets speed) and the generated backyard block walls show how built things change movement and cover.

## Decisions to make here (then record them in this brief)

- Where the base is (a real ranch or house near New River) and how big the buildable area is.
- What can be built: walls and gates, beds and shelter, water storage and collection, gardens, kitchens, workbenches, watch posts.
- People and their needs live in `people.md`; stores, production chains and civics in `settlement.md`. This brief owns construction, the base layout and the tasks buildings offer.
- Time follows the two clocks in the foundation.
- Defence: raids on the base become tactical fights (with `combat.md`); built walls and posts are real cover.

## Decisions (proposed in the one-page design, 2026-10-03)

Design doc (Claude Docs): https://claude.ai/code/artifact/04a6b91c-6149-4653-9bf1-f0acacc18d98. Its People and Resources sections are proposals handed to `people.md` and `settlement.md`; this brief keeps only what follows.

- **Site**: the region `home` point in New River, sector (15, 31). Buildable lot 96 × 96 m (48 × 48 cells on the 2 m grid), starting from one real house picked from the bake. Sized for the foundation's 15–30 survivors.
- **Day shape** (world clock): outdoor jobs in the cool hours 06–10 and 18–22; indoor jobs and rest in the heat 10–18 (outdoor work at half speed); sleep 22–06 with two on watch. Away from the camera the base settles hourly (foundation cadence).
- **First ten buildables** (cost in loot-category units, build time in work-hours at Build 1, −15% per level above):

| Thing | Footprint (cells) | Grid kind | Cover | Cost, time | Effect |
|---|---|---|---|---|---|
| Wall | 1 × 1 | `wall` | full | 2 shelter, 3 h | blocks movement and shots |
| Gate | 2 × 1 | `wall` when shut | full when shut | 3 shelter + 1 goods, 6 h | shut at night or on alarm |
| Bed | 1 × 1 indoors | none | none | 1 shelter, 2 h | full rest instead of half |
| Bunkhouse | 4 × 3 | `building` | full | 12 shelter + 2 goods, 24 h | 4 beds, midday shade |
| Water tank | 2 × 2 | `building` | full | 4 goods + 2 shelter, 8 h | stores 1,000 L |
| Rain catcher | 3 × 2 | none | none | 3 shelter + 1 goods, 6 h | 24 m² roof, 24 L per mm of rain into a tank |
| Garden bed | 2 × 3 | none (yard, 0.8) | none | 1 shelter, 4 h | a production site for `settlement.md` |
| Kitchen | 2 × 2 | none | half | 2 shelter + 1 goods, 6 h | a production site (cooking) |
| Workbench | 1 × 2 | none | half | 2 shelter + 2 goods, 6 h | a production site (crafting, repair) |
| Watch post | 2 × 2, 3 m platform | `building`, walkable top | full, +15 height | 6 shelter, 12 h | spots at 60 m; reveals neighbouring sectors |

- **What buildings give other topics**: storage capacity and conditions (tank litres, stockpile cells of 10 units, shade) and production sites to `settlement.md`; beds, shade and amenities that `people.md` reads for sleep and mood; build, haul and repair tasks offered to job choice in the shared task shape (`tools/sim/README.md`).

Needs from other topics: a grid kind or flag for built half cover (`combat.md`, `tactical-maps.md`); a runtime call that sets a cell's kind the way the bake does and refreshes pathing (`tactical-maps.md`).

## Interfaces

- Survivors are FigureKit figures (`models.md`) with procedural motion (`animation.md`); ask those topics for work animations and base props rather than final-building them here.
- Built things must write into the movement grid and cover (kinds `building`, `wall`) the way the bake does, so pathing and combat respect them.
- Squads are formed from base people and come back with loot (with `strategy-map.md`).

## First tasks

1. ~~A one-page design~~ done (see Decisions).
2. A prototype on the real home sector: place walls, a water tank and beds on the 2 m grid; people walk to jobs; water drains per person per hour.
3. Agree the hand-over with `strategy-map.md` (forming squads, returning loot).

## Out of scope

The ground itself (`tactical-maps.md`), the fight when the base is raided (`combat.md`).
