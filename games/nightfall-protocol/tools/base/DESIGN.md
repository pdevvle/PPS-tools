# The ranch: one-page design (building, the logistic layer)

Topic: `briefs/building.md`. This topic owns **construction, the base layout and the tasks buildings offer**. Needs, health and job choice belong to `people.md`. Stores, spoilage, production accounting and civics belong to `settlement.md`. Numbers from those topics are written here as **working assumptions** until they settle them. Changes to other topics are marked **(proposed)** and listed in the pull request.

## The place

- **The ranch** is a real desert lot on the south side of West New River Road, about 150 m west of North 32nd Avenue. It sits inside the campaign's home sector (region sector 16, 31) and the baked New River block (sector `s_3_2`).
- **Buildable area**: 140 × 140 m, which is 70 × 70 cells on the 2 m movement grid. That is room for the foundation's 15–30 people. In block coordinates it runs x 650–790 and z −30–110 (centre 720, 40). In region coordinates add (134, 2986).
- **The ground**: open desert and brush, falling gently (about 3 %) south to the sand wash, which crosses the south-east corner. The road gives a way in from the north, and the wash a way in from the south.
- **Claimed rather than built**: things already on the lot are taken over, and their insides come from `interiors.md`.

  | Thing | Where (block) | Use |
  |---|---|---|
  | House, about 310 m² | (713, 14) | Shelter and beds; indoor shade |
  | Barn, about 160 m² | (694, 23) | Indoor store (settlement's storage conditions) |
  | Shed, about 100 m² | (710, 53) | Workshop |
  | Two outbuildings by the wash | (653, 103), (681, 106) | Tear down for materials |
  | Old well with a dead electric pump | Beside the barn (placed by us; not in OpenStreetMap) | Repair as a hand pump (see the table below). `lore.md`: "a ranch may have a hand pump and stored diesel" |

## A day at the ranch (early summer)

| Time | What the base offers |
|---|---|
| 05:00–10:00 | Outdoor tasks: building, gardens, hauling, collecting water |
| 10:00–18:00 | Heat. Shaded and indoor tasks (kitchen, workbench, doctor), and rest in shade. Outdoor tasks stay open but are marked heat-exposed |
| 18:00–22:00 | Outdoor tasks again; the evening meal |
| 22:00–05:00 | Beds, and watch posts manned in turns |

- **The loop**: squads go out and bring loot back. Building turns it into water storage, food production, beds and cover. That keeps more people alive and lets bigger squads go further. Raiders who see the ranch come to take it.
- **Water is the pressure**, but the rate belongs to `people.md`. At today's rates, with heat-exposed work only in the cool hours, a person uses about 10 L a day, and six people about 60 L. Building's answer is containers and sources: the seep, the pump and tanks.

## The first ten buildable things

Sizes are in 2 m grid cells. Times are work hours at average skill. Costs are in the strategy layer's stock units.

| # | Thing | Size | Cost | Time | Tasks it offers | Sets for `settlement.md` | Grid kind and cover |
|---|---|---|---|---|---|---|---|
| 1 | Wall section or gate | 1 cell edge, 1.8 m high | 1 material (a gate adds 1 part) | 1 h | Repair | — | `wall`, full cover; a gate opens for the ranch's own people |
| 2 | Barricade (sandbags, scrap) | 1 | 1 material | 0.5 h | Repair; a guard position | — | Blocks movement; **half cover (proposed, combat)** |
| 3 | Bed | 1 × 2 | 1 material | 1 h | Sleep; treat a patient | Beds: one sleeper | Furniture |
| 4 | Shade ramada | 2 × 2 | 2 materials | 2 h | Rest in shade; shaded work spot | Amenity: shade | Posts only; passable |
| 5 | Water tank | 2 × 2 | 4 materials, 2 parts | 6 h | Fill, draw | Water storage +1,000 L | `building`, full cover |
| 6 | Wash seep | 1, in the sand wash | — | 6 h of digging | Collect water | Water source, about 25 L a day (assumed) | Stays `sand wash` |
| 7 | Hand pump on the old well | Existing well | 4 parts | 4 h of repair | Pump water (heat-exposed) | Water source, about 60 L a day of pumping (assumed) | `building`, half cover |
| 8 | Garden bed | 3 × 3 | 1 material, 5 L water | 2 h | Water and tend; harvest | Food source (yield is settlement's) | `yard` speed; passable |
| 9 | Kitchen (cook fire and table) | 2 × 2 | 2 materials, 1 part | 3 h | Cook | Cooking capacity; amenity: hot meals | `building`, full cover |
| 10 | Watch post (raised 3 m) | 2 × 2 | 3 materials, 1 part | 6 h | Keep watch | — | `building` base and a walkable deck. Watch reaches 2.5 km while manned (**proposed, strategy**). In a fight, +15 aim from height and half cover from the parapet |

- The shed's workbench is claimed with the shed, so it is not on the list. A workbench offers Craft and Salvage, and its recipes are settlement's.
- Every thing also offers **Build** (or Repair) while unfinished and **Deconstruct** (which returns half the cost).
- Materials are carried to the site from the store by a **Haul** task.

## Tasks: what building hands to job choice

- Every thing offers tasks as plain data. Survivors pick among them by `people.md`'s utility score, and the player only sets priorities (foundation: indirect control). A task looks like this:

  ```
  { id, kind:'build'|'repair'|'deconstruct'|'haul'|'cook'|'craft'|'tend'|'collect_water'|'pump'|'watch'|'sleep'|'rest_shade'|'treat',
    thing, cell:[i,j] /*where to stand on the 2 m grid*/, skill /*e.g. 'building'*/, hours /*at average skill*/,
    inputs:{…}, outputs:{…} /*stock units; settlement applies them*/, heat:'exposed'|'shaded'|'indoor', slots /*people at once*/, priority }
  ```

- Walking to a task is real. The distance on the 2 m grid at terrain speeds goes into the utility score as distance, so a far tank costs real time.
- **Placing a thing** writes its cells into the movement grid (`kind`, `sp`), and its walls into the wall list, the same way the bake does. Pathing and combat then treat it like baked ground. Unfinished things are a site, passable and without cover.

## Working assumptions from other topics

- **`people.md`**:
  - Needs are water, food, sleep, health and mood.
  - Skills named here: building, growing, cooking, medicine, mechanics, shooting and scouting.
  - The game starts with six survivors, matching the campaign's two squads (4 + 2).
- **`settlement.md`**:
  - Stores in the strategy units: rations, med kits, parts, L fuel, gear, L water, materials and trade goods.
  - The barn counts as indoor storage. Water needs a container: about 400 L in the house's barrels before any tank.
  - **Starting stock (proposed, strategy and settlement)**: 400 L water, 30 rations, 4 med kits, 6 parts, 10 L fuel, 6 gear, 20 materials and 5 trade goods.

## Time

- Building follows the foundation's two clocks. Build, repair and every other task progress on the **world clock**, settled continuously, so any stretch can be fast-forwarded in one step. Nothing in building uses the life clock.
- **The clock runs at the ranch (proposed, strategy)** while a task is open (something being built, cooked or tended). When the ranch is idle and no squad is moving, the clock holds as it does now.
- **While squads are away** the ranch keeps going:
  - When the ranch is on screen, people walk the real grid.
  - When it is off screen, walking time is taken from grid distances, and nothing is drawn.

## Defence

- The ranch watches 1.5 km out (campaign `HOME_SIGHT`), or 2.5 km with a manned watch post.
- A raid is an encounter with `where` at the ranch. Whoever saw first strikes first. The defenders are the people at home on guard and anyone who picks up gear.
- The fight is `combat.md`'s, on the same ground, so built walls, barricades and posts are real cover. Afterwards building applies damage to things (each has HP and needs Repair), and settlement applies losses to stock.

## Hand-over with the strategy map (task 3, draft)

- Squads are formed at the ranch from survivor records (`people.md`).
- **(proposed, strategy)**: a squad gets `members:[id]`, and `people` stays as a head count for compatibility.
- The base's part:
  - Water for the trip is drawn from tanks.
  - Returning loot is unloaded at the barn by Haul tasks.
  - A squad that comes home wounded makes Treat tasks at beds.

## Out of scope here

The ground itself (`tactical-maps.md`), the raid fight (`combat.md`), building insides (`interiors.md`), work animations and props (`models.md`, `animation.md`), needs and job choice (`people.md`), and stores, recipes and spoilage (`settlement.md`).
