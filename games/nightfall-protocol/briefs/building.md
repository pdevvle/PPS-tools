# Brief: building (the logistic layer)

Read `00-foundation.md` first.

## Goal

The base: the survivors' home where people live, work, build and use what the squads bring back. RimWorld-like management on real ground, feeding and fed by the strategic layer.

## Files

`tools/base/` (see its README):
- `DESIGN.md`, the merged design
- `cut_site.py`
- `ranch-core.js`, the rules
- `ranch-main.js`, the page
- `base-head.html`
- `build.sh`, `test.js` and `page-test.js`

Also `data/base/ranch_site.json` and `mockups/base.html`.

## Where it stands

- **Design**: done and merged (first task 1). Two one-page designs were drafted in parallel and are now one; see Decisions. The details are in `tools/base/DESIGN.md`.
- **Prototype** (first task 2, done): `mockups/base.html` runs on 760 × 500 m of the baked New River block. Published as the Base Builder artifact: https://claude.ai/artifact/VHZBkjgVgmS823qTqJAeVU
  - **Founding**: the base can be founded anywhere on the cut. Two base points are suggested.
  - **Placing**: all fourteen buildables can be placed on the 2 m grid. You can also repair the old well or take an outbuilding apart.
  - **People**: six `People` survivors choose the work with `People.score`, fetch materials, walk the real ground and build. They refill canteens from the base's water and rest indoors in the heat. At night they sleep on cots, in the bunkhouse or in the house, with two on watch.
  - **Grid**: finished things write kind and cover into the grid, and paths go round them. Gates shut at night.
  - **Construction and layout**: sites are marked out with stakes and string, then go through materials on site, groundwork, framing, walls and roof. Builders work and carriers bring materials. The build card shows the cost against the stores, the time, the footprint and the grid effect. Sites carry stage labels, and a construction queue has priority and cancel. **▶ Watch a build** walks through a bunkhouse from choosing it to done.
  - **Tests**: the rules are tested in Node (`test.js`) and the page in Chromium (`page-test.js`).

What exists to build on:
- The home sector is near New River on the region map (`data/region/region_i17.json` `home`), inside the baked New River block, so the base can sit on the streamed tactical ground.
- Loot categories (food, medicine, tools, fuel, gear, water, shelter, goods) and water use per person per hour (foundation).
- The 2 m movement grid (walls and buildings block, terrain sets speed) and the generated backyard block walls show how built things change movement and cover.

## Decisions (keep)

This merges the two one-page designs: the ranch design (`tools/base/DESIGN.md`) and the 2026-10-03 design doc (Claude Docs: https://claude.ai/code/artifact/04a6b91c-6149-4653-9bf1-f0acacc18d98). The doc's People and Resources sections are proposals handed to `people.md` and `settlement.md`.

- **Site: bases are freely placed.**
  - A base is a **140 × 140 m** square (70 × 70 cells on the 2 m grid), founded anywhere on baked ground.
  - Buildings standing on it are claimed rather than built: the biggest house is home (shelter, the water barrels), the next building the store, and the next the workshop. Small outbuildings can be taken apart for 6 shelter each.
  - A base with a house has an old well. Its electric pump died with the grid, and a hand pump is a repair (`lore.md`).
  - Two base points are suggested:
    - the **ranch lot** in the campaign's home sector (16, 31), south of West New River Road;
    - the region's **home point** in sector (15, 31).
- **Day shape** (world clock):
  - Outdoor jobs in the cool hours, 06–10 and 18–22.
  - Indoor jobs and rest in the heat, 10–18. Outdoor work then goes at half speed.
  - Sleep 22–06, with two on watch.
- **Buildables**: building.md's ten with their numbers, plus four from the ranch design with stats inferred from them (marked *). Costs are in loot-category units. Build time is in work-hours at Build 1, −15% per level above.

| Thing | Footprint (cells) | Grid kind | Cover | Cost, time | Effect |
|---|---|---|---|---|---|
| Wall | 1 × 1 | `wall` | full | 2 shelter, 3 h | blocks movement and shots |
| Gate | 2 × 1 | `wall` when shut | full when shut | 3 shelter + 1 goods, 6 h | shut at night; the base's own people always pass |
| Barricade* | 1 × 1 | `wall` | half | 1 shelter, 1.5 h | a cheap fighting position |
| Bed | 1 × 1 | none (walking ×0.6) | none | 1 shelter, 2 h | full rest instead of half; a cot outdoors until interiors furnish rooms |
| Bunkhouse | 4 × 3 | `building` | full | 12 shelter + 2 goods, 24 h | 4 beds, midday shade |
| Shade ramada* | 2 × 2 | none | none | 3 shelter, 4 h | shade for 4 outdoors |
| Water tank | 2 × 2 | `building` | full | 4 goods + 2 shelter, 8 h | stores 1,000 L |
| Rain catcher | 3 × 2 | none | none | 3 shelter + 1 goods, 6 h | 24 m² roof, 24 L per mm of rain into a tank |
| Wash seep* | 1 × 1, in a sand wash | `wash` | none | nothing, 8 h of digging | 25 L a day to haul |
| Hand pump* | 1 × 1, on the old well | unchanged | half | 3 goods, 6 h | 15 L an hour of pumping, up to 60 L a day |
| Garden bed | 2 × 3 | none (yard, 0.8) | none | 1 shelter, 4 h | a production site for `settlement.md`; tended daily with 3 L |
| Kitchen | 2 × 2 | none | half | 2 shelter + 1 goods, 6 h | a production site (cooking) |
| Workbench | 1 × 2 | none | half | 2 shelter + 2 goods, 6 h | a production site (crafting, repair) |
| Watch post | 2 × 2, 3 m platform | `building`, walkable top | full, +15 height | 6 shelter, 12 h | two on watch at night; spots at 60 m; reveals neighbouring sectors |

- **Grid writes**: the cover is a per-cell value (0 none, 1 half, 2 full) kept beside `kind` and `sp`. A gate cell also carries a gate flag that lets the base's own people through. Unfinished sites are passable and give no cover.
- **What buildings give other topics**:
  - To `settlement.md`: storage capacity and conditions (tank litres, stockpile cells of 10 units, shade) and production sites.
  - To `people.md`: beds, shade and amenities, which it reads for sleep and mood.
  - To job choice: build, haul, grow, guard and repair tasks, offered in the shared task shape (`tools/sim/README.md`) and scored with `People.score`.
- **Time**: building runs on the world clock, settled continuously, and keeps running while squads are away. Off screen, walking times are estimated; the foundation's cadence settles the base hourly.

## Proposed for other topics (flagged in the pull request)

- **combat, tactical-maps**:
  - Built half cover needs a value combat reads beyond `wall` and `building`; the prototype keeps a per-cell cover array.
  - A runtime call that sets a cell's kind the way the bake does and refreshes pathing.
- **strategy-map**:
  - The clock also runs while the base has an open task.
  - Squads get `members:[id]`, and `people` stays as a head count.
- **settlement**:
  - Production numbers are assumed here until settlement sets them: the seep, the pump, and 400 L of barrels before a tank.
  - A starting stock: 400 L water, 30 rations, 4 med kits, 6 parts, 10 L fuel, 6 gear, 40 shelter and 12 goods. At `People`'s rates, 30 rations last six people about 4½ days, so either the start needs more food or the first runs have to find it.
- **people**: the base hands water out through a 2 L canteen each person carries and refills at a water point. Food comes straight from the stores until settlement rations it.

## Scope and open items

- People and their needs live in `people.md`; stores, production chains and civics in `settlement.md`. This brief owns construction, the base layout and the tasks buildings offer.
- Time follows the two clocks in the foundation.
- Defence: raids on the base become tactical fights (with `combat.md`); built walls and posts are real cover.
- Stockpile cells (10 units each) are in the design but not placed in the prototype yet. Materials come from the store's door.

## Interfaces

- Survivors are FigureKit figures (`models.md`) with procedural motion (`animation.md`); ask those topics for work animations and base props rather than final-building them here.
- Built things must write into the movement grid and cover (kinds `building`, `wall`) the way the bake does, so pathing and combat respect them.
- Squads are formed from base people and come back with loot (with `strategy-map.md`).

## First tasks

1. ~~A one-page design: the loop of a day at the base, the first ten buildable things, people's needs and jobs, the resource list.~~ Done, and the two drafts merged (see Decisions).
2. ~~A prototype on the real home sector: place walls, a water tank and beds on the 2 m grid; people walk to jobs; water drains per person per hour.~~ Done: `mockups/base.html`, on freely founded bases.
3. Agree the hand-over with `strategy-map.md` (forming squads, returning loot).

## Out of scope

The ground itself (`tactical-maps.md`), the fight when the base is raided (`combat.md`).
