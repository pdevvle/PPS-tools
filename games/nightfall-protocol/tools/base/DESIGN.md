# The base: one-page design (building, the logistic layer)

Topic: `briefs/building.md`. This topic owns **construction, the base layout and the tasks buildings offer**. Needs, health and job choice belong to `people.md`. Stores, spoilage, production accounting and civics belong to `settlement.md`.

This page merges the two one-page designs drafted in parallel:
- the ranch design;
- the 2026-10-03 design doc (Claude Docs: https://claude.ai/code/artifact/04a6b91c-6149-4653-9bf1-f0acacc18d98).

The doc's numbers are kept. The ranch design adds free placement of the base, four buildables (marked *, with stats inferred from the doc's) and the claimed buildings. Changes to other topics are marked **(proposed)**.

## The place: a base can go anywhere

- **A base is a 140 × 140 m square**, 70 × 70 cells on the 2 m movement grid. It can be founded anywhere on baked ground and has room for the foundation's 15–30 people.
- **Claimed rather than built**: buildings standing on the square are taken over. Their insides come from `interiors.md`.

  | Role | Which building | Use |
  |---|---|---|
  | Home | The biggest house | Shelter: rest and sleep indoors. The water barrels, 400 L |
  | Store | The next building | Materials are fetched from its door. Stockpile cells come later |
  | Workshop | The next | A production site for settlement (crafting) |
  | Outbuildings | The rest, if small | Taken apart for 6 shelter each (6 h) |
  | Old well | Beside the store, on any base with a house | Its electric pump died with the grid. A hand pump is a repair (`lore.md`: "a ranch may have a hand pump and stored diesel") |

- **Two suggested base points**. Both are tested in the prototype, as is a base in open ground.

  | Base point | Where | Block x | Block z | On it |
  |---|---|---|---|---|
  | Ranch lot | The campaign's home sector (16, 31), on the south side of West New River Road, about 150 m west of North 32nd Avenue | 650–790 | −30–110 | A house of about 310 m², a barn of about 160 m², a shed and two small outbuildings. The sand wash crosses its south-east corner |
  | Region home point | Sector (15, 31) | 166–306 | 162–302 | A cluster of small buildings |

## A day at the base (early summer, world clock)

| Time | What the base offers |
|---|---|
| 06:00–10:00 | Outdoor jobs: building, gardens, hauling and pumping water |
| 10:00–18:00 | Heat. Indoor jobs and rest indoors or in shade. Outdoor work goes on at half speed, and `People.score` already marks it down for heat |
| 18:00–22:00 | Outdoor jobs again |
| 22:00–06:00 | Sleep on cots, in the bunkhouse or in the house, with two on each watch post |

- **The loop**: squads go out and bring loot back. Building turns it into water storage, beds, shade and cover. That keeps more people alive and lets bigger squads go further. Raiders who see the base come to take it.
- **Water is the pressure**. With People's rates over the early-summer heat, six people use about 70 L a day. 400 L of barrels last under a week. The seep and the pump together bring in 85 L a day, and rain comes only with the monsoon (a weather model to come).

## The buildables

- Costs are in loot-category units. Time is in work-hours at Build 1; each level above takes 15% off.
- The doc's ten keep its numbers. The four marked * are inferred: a barricade is half a wall, the ramada sits between a garden bed and a kitchen, the seep's dig matches a tank's labour, and the pump is costed in goods like the tank's hardware.

| Thing | Cells | Grid kind | Cover | Cost, time | Gives |
|---|---|---|---|---|---|
| Wall | 1 × 1 | `wall` | full | 2 shelter, 3 h | Blocks movement and shots |
| Gate | 2 × 1 | `wall` when shut | full when shut | 3 shelter + 1 goods, 6 h | Shut at night; the base's own people always pass |
| Barricade* | 1 × 1 | `wall` | half | 1 shelter, 1.5 h | A cheap fighting position |
| Bed | 1 × 1 | none (walking ×0.6) | none | 1 shelter, 2 h | Full rest instead of half; a cot outdoors until rooms are furnished |
| Bunkhouse | 4 × 3 | `building` | full | 12 shelter + 2 goods, 24 h | 4 beds, midday shade |
| Shade ramada* | 2 × 2 | none | none | 3 shelter, 4 h | Shade for 4 outdoors |
| Water tank | 2 × 2 | `building` | full | 4 goods + 2 shelter, 8 h | Stores 1,000 L |
| Rain catcher | 3 × 2 | none | none | 3 shelter + 1 goods, 6 h | 24 L per mm of rain into the tanks |
| Wash seep* | 1 × 1, in a sand wash | `wash` | none | nothing, 8 h | 25 L a day to haul |
| Hand pump* | The old well | unchanged | half | 3 goods, 6 h | 15 L an hour of pumping, 60 L a day |
| Garden bed | 2 × 3 | none (yard, 0.8) | none | 1 shelter, 4 h | A production site; tended daily with 3 L |
| Kitchen | 2 × 2 | none | half | 2 shelter + 1 goods, 6 h | A production site (cooking) |
| Workbench | 1 × 2 | none | half | 2 shelter + 2 goods, 6 h | A production site (crafting, repair) |
| Watch post | 2 × 2, 3 m platform | `building` | full, +15 height | 6 shelter, 12 h | Two on watch at night; spots at 60 m; reveals neighbouring sectors |

- **Grid writes**: a finished thing writes `kind`, `sp` and a per-cell cover value (0, 1 or 2) the way the bake does, so pathing and combat treat it like baked ground. Unfinished sites are passable and give no cover. A gate carries a flag that lets the base's own people through even when it is shut.
- Things may not go in a sand wash, which floods, except the seep.

## Tasks: what building hands to job choice

- Things offer tasks in the shared shape, `{id, kind, skill, where:{x,z}, hours, urgency, outdoor, heavy}` (`tools/sim/README.md`). Each person picks the best with `People.score`.
- Building adds only the day shape: sleep pulls at night, two take the watch, and whoever has stood it least goes next.
- The kinds offered:
  - `build`: fetch the materials from the store door, carry them to the site and work. A bunkhouse takes 3 builders at once and a watch post 2.
  - `haul`: seep water to the tanks, or a turn on the pump.
  - `grow`: tend a garden.
  - `guard`: the watch post.
  - `drink`: refill a canteen at the barrels or a tank.
  - `sleep` and `rest`.
- Walking to a task is real: A* over the 2 m grid at terrain speed, slowed by thirst and low capacity (`People.capacity`).

## People and stores (stand-ins until the topics are wired)

- **People**: survivors are `People.create` records. Every half minute, `People.demand` and `People.step` settle each body.
  - Water reaches the body only from a 2 L **canteen** that the person refills at a water point. That is building's way of making water physical.
  - Food comes straight from the stores until `Settlement.ration` takes over.
- **Starting stock (proposed, settlement and strategy)**: 400 L water, 30 rations, 4 med kits, 6 parts, 10 L fuel, 6 gear, 40 shelter and 12 goods. At People's rates, 30 rations last six people about 4½ days.

## Defence

- The fight is `combat.md`'s, on the same ground. Built walls, barricades and posts are real cover.
- Afterwards building applies damage to things (each will have HP and need repair), and settlement applies losses to stock.

## Hand-over with the strategy map (task 3, draft)

- Squads are formed at the base from survivor records.
- **(proposed, strategy)**: a squad gets `members:[id]`, and `people` stays as a head count.
- Water for the trip is drawn from the tanks. Returning loot is unloaded at the store, and wounded people go to beds.
