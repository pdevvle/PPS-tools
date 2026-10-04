# Brief: building (the logistic layer)

Read `00-foundation.md` first.

## Goal

The base: the survivors' home where people live, work, build and use what the squads bring back. RimWorld-like management on real ground, feeding and fed by the strategic layer.

## Files

`tools/base/` (`DESIGN.md`, `cut_site.py`, `ranch-core.js` the rules, `ranch-main.js` the page, `base-head.html`, `build.sh`, `test.js`, `page-test.js`; see its README), `data/base/ranch_site.json`, and `mockups/base.html`.

## Where it stands

- **Design**: the one-page design is in `tools/base/DESIGN.md` (first task 1, done).
- **Prototype** (first task 2, done): `mockups/base.html` runs on the real lot.
  - Order walls (or drag a line of them), gates, barricades, beds, a ramada, a tank, a seep, a garden, a kitchen and a watch post onto the 2 m grid. You can also repair the old well or tear down an outbuilding.
  - Six survivors fetch materials from the barn and build. They drink, rest in shade through the heat and sleep on beds or in the house.
  - Water drains at the foundation rate. Finished things write `wall` or `building` and their cover into the grid, and paths go round them.
  - The rules are in `tools/base/ranch-core.js` and tested in Node (`test.js`); the page is checked in Chromium (`page-test.js`).

What exists to build on:
- The home sector is near New River on the region map (`data/region/region_i17.json` `home`), inside the baked New River block, so the base can sit on the streamed tactical ground.
- Loot categories (food, medicine, tools, fuel, gear, water, shelter, goods) and water use per person per hour (foundation).
- The 2 m movement grid (walls and buildings block, terrain sets speed) and the generated backyard block walls show how built things change movement and cover.

## Decisions (keep)

The details and numbers are in `tools/base/DESIGN.md`.

- **Where**: the ranch is a real lot south of West New River Road, about 150 m west of North 32nd Avenue. It is in the campaign's home sector (16, 31) and block sector `s_3_2`.
  - Buildable area: 140 × 140 m (70 × 70 cells), block x 650–790, z −30–110.
  - Claimed rather than built: a house (shelter, beds), a barn (indoor store), a shed (workshop and workbench), and an old well whose dead electric pump is repaired as a hand pump.
  - Two small outbuildings can be torn down for materials.
  - The sand wash crosses the south-east corner.
- **First ten buildables**: wall or gate, barricade, bed, shade ramada, water tank, wash seep, hand pump (a repair), garden bed, kitchen, watch post.
  - Each has a footprint, a cost in stock units, work hours, the tasks it offers, what it sets for settlement (storage, sources, amenities), and its grid kind and cover.
- **Tasks**: things offer tasks as plain data `{kind, thing, cell, skill, hours, inputs, outputs, heat, slots, priority}`. Survivors choose among them by `people.md`'s utility score, and settlement applies the inputs and outputs.
- **Grid**: placed things write `kind` and `sp` into the movement grid and walls into the wall list, as the bake does. Unfinished sites are passable and give no cover.
- **Day**: outdoor tasks 05:00–10:00 and 18:00–22:00; shaded and indoor tasks in the heat; beds and the night watch 22:00–05:00.
- **Grid writes** (as built): wall and barricade cells are `wall` (full or half cover); a gate is `wall` with a gate flag that lets the ranch's own people through; tank and kitchen are `building` (full); the watch post is `building` (half); beds and gardens slow walking. The cover is a per-cell value (0 none, 1 half, 2 full) beside `kind` and `sp`.
- **Time**: building runs on the world clock, settled continuously, and keeps running while squads are away. Off screen, walking times are estimated.

## Proposed for other topics (flagged in the pull request)

- **combat**: barricades, the pump and watch-post parapets give half cover, so built things need a cover value beyond `wall` (full) and `building` (full).
- **strategy-map**:
  - The clock also runs while the ranch has an open task.
  - Squads get `members:[id]`, and `people` stays as a head count.
  - A manned watch post widens the ranch's watch from 1.5 to 2.5 km.
  - A starting stock in `newGame`: 400 L water, 30 rations, 4 med kits, 6 parts, 10 L fuel, 6 gear, 20 materials and 5 trade goods (with settlement).
- **settlement**: production numbers assumed in the design until settlement sets them: the seep gives about 25 L a day, the hand pump about 60 L a day of pumping, and storage holds about 400 L before a tank.

## Scope and open items

- People and their needs live in `people.md`; stores, production chains and civics in `settlement.md`. This brief owns construction, the base layout and the tasks buildings offer.
- Time follows the two clocks in the foundation.
- Defence: raids on the base become tactical fights (with `combat.md`); built walls and posts are real cover.

## Interfaces

- Survivors are FigureKit figures (`models.md`) with procedural motion (`animation.md`); ask those topics for work animations and base props rather than final-building them here.
- Built things must write into the movement grid and cover (kinds `building`, `wall`) the way the bake does, so pathing and combat respect them.
- Squads are formed from base people and come back with loot (with `strategy-map.md`).

## First tasks

1. ~~A one-page design: the loop of a day at the base, the first ten buildable things, people's needs and jobs, the resource list.~~ Done: `tools/base/DESIGN.md`.
2. ~~A prototype on the real home sector: place walls, a water tank and beds on the 2 m grid; people walk to jobs; water drains per person per hour.~~ Done: `mockups/base.html`.
3. Agree the hand-over with `strategy-map.md` (forming squads, returning loot).

## Out of scope

The ground itself (`tactical-maps.md`), the fight when the base is raided (`combat.md`).
