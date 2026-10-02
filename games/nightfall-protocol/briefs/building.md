# Brief: building (the logistic layer)

Read `00-foundation.md` first.

## Goal

The base: the survivors' home where people live, work, build and use what the squads bring back. RimWorld-like management on real ground, feeding and fed by the strategic layer.

## Where it stands

Not started. What exists to build on:
- The home sector is near New River on the region map (`data/region/region_i17.json` `home`), inside the baked New River block, so the base can sit on the streamed tactical ground.
- Loot categories (food, medicine, tools, fuel, gear, water, shelter, goods) and water use per person per hour (foundation).
- The 2 m movement grid (walls and buildings block, terrain sets speed) and the generated backyard block walls show how built things change movement and cover.

## Decisions to make here (then record them in this brief)

- Where the base is (a real ranch or house near New River) and how big the buildable area is.
- What can be built: walls and gates, beds and shelter, water storage and collection, gardens, kitchens, workbenches, watch posts.
- People: needs (water, food, sleep, health, morale), skills, jobs and a work queue.
- Resources: stockpiles by loot category; what turns into what.
- Time: how base time relates to the map clock; what happens at the base while squads are away.
- Defence: raids on the base become tactical fights (with `combat.md`); built walls and posts are real cover.

## Interfaces

- Survivors are FigureKit figures (`models.md`) with procedural motion (`animation.md`); ask those topics for work animations and base props rather than final-building them here.
- Built things must write into the movement grid and cover (kinds `building`, `wall`) the way the bake does, so pathing and combat respect them.
- Squads are formed from base people and come back with loot (with `strategy-map.md`).

## First tasks

1. A one-page design: the loop of a day at the base, the first ten buildable things, people's needs and jobs, the resource list.
2. A prototype on the real home sector: place walls, a water tank and beds on the 2 m grid; people walk to jobs; water drains per person per hour.
3. Agree the hand-over with `strategy-map.md` (forming squads, returning loot).

## Out of scope

The ground itself (`tactical-maps.md`), the fight when the base is raided (`combat.md`).
