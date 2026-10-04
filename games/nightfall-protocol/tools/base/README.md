# The ranch (the logistic layer)

Building's topic (`../../briefs/building.md`). `DESIGN.md` is the one-page design. This folder also holds the first prototype, `../../mockups/base.html`, which runs on the real lot.

- `cut_site.py` cuts the ranch's ground out of the baked New River block into `../../data/base/ranch_site.json`. The cut is 200 × 200 m of sector `s_3_2` and holds:
  - heights on the 4 m grid
  - the 2 m movement grid (kind and speed)
  - buildings, with the house, barn, shed and two outbuildings marked as claimed
  - walls, plants, roads, the wash and areas

  Rerun it when the bake changes.
- `ranch-core.js` holds the rules: placing things, the grid writes, tasks, people walking to them, and water. It has no rendering, so it runs in the page and in Node.
- `ranch-main.js` is the page: the ground, buildings and plants in the streaming page's ink-faceted look, the built things, FigureKit people moved by `Motion`, the build tools and the panels.
- `base-head.html` is the page's markup and style.
- `./build.sh` assembles `mockups/base.html`. The site data is inlined, so the page opens straight from disk. The published Artifact is the same page without its first two lines.
- `node test.js` checks the rules.
- `page-test.js` checks the page in Chromium: it places a tank and a wall line with the mouse, then runs a day and a night. Give it `THREE` (a path to three r128's `three.min.js`) and optionally a folder for screenshots.

## What the prototype does

- **Placing**: pick a thing, then click the ground, or drag for a line of walls or barricades. R rotates beds. The ghost turns red where a thing can't go, and the tip says why: off the buildable area, on something, on blocked ground, or a seep away from the sand wash.
- **Other orders**:
  - **Repair well** orders the hand pump on the old well beside the barn. Its electric pump is dead.
  - **Tear down** takes an outbuilding by the wash apart for 6 materials. Its cells become open ground.
  - **Cancel** returns a planned thing's materials to the store.
- **Grid writes**: a finished thing writes the movement grid as the bake does, and the **Movement grid** view shows the result. All sizes are in 2 m cells.

  | Thing | Size | Kind | Cover |
  |---|---|---|---|
  | Wall | 1 cell | `wall` | Full |
  | Barricade | 1 cell | `wall` | Half (blue in the view) |
  | Gate | 1 cell | `wall` | Full; passable for the ranch's own people |
  | Tank, kitchen | 2 × 2 | `building` | Full |
  | Watch post | 2 × 2 | `building` | Half |
  | Bed | 1 × 2 | Unchanged (slows walking to 0.6) | None |
  | Garden bed | 3 × 3 | Unchanged (slows walking to 0.8) | None |

  Paths go round blocked cells. People standing on a cell that becomes solid step off it.
- **People**: six survivors.
  - When a task ends, each takes the best one on offer. The score is a stand-in for `people.md`'s utility AI.
  - Tasks on offer: fetch materials from the barn door and build, drink at the house barrels or a tank, sleep on a bed or in the house, rest in shade in the heat, pump, collect seep water, tend a garden, keep watch, and idle near the house.
  - They walk the 2 m grid at the foundation's 5 km/h, times the terrain speed, using A* that costs time (as the streaming page does).
  - Work speed is 0.6 + 0.08 × building skill.
- **Day**:
  - Outdoor work runs 05:00–10:00 and 18:00–22:00.
  - From 10:00 to 18:00 people rest in the house or under a ramada. Outdoor work stops unless **Outdoor work through the heat** is on.
  - Everyone sleeps 22:00–05:00. One person keeps watch if there is a post, and the watch rotates.
- **Water**:
  - The rate is the foundation's 0.5 L per person per hour, doubled from 10:00 to 18:00. That is 16 L a person a day, or 96 L for six.
  - People drink when 2 L behind. Above 4 L they are thirsty and walk at ×0.8, and above 8 L they are dehydrated, walk at ×0.6 and get the wounded ink.
  - Storage is 400 L in the house barrels, plus 1,000 L per tank.
  - The seep fills 25 L a day for collecting. The pump gives 15 L an hour of pumping, up to 60 L a day.
- **Clock**: speeds are 15×, 60× and 600× (600× is the map's 1×, 10 game minutes a second). Any stretch settles in half-minute steps; ten days take about 1.4 s in Node.

## Stand-ins until other topics deliver

- **`people.md`**: the water rate, the thirst thresholds and job choice.
- **`settlement.md`**: stores (the strategy layer's units), the starting stock, seep and pump yields, and storage.
- **`interiors.md`**: inside the house. People who are inside are simply hidden.
- **`models.md` and `animation.md`**: work poses. `Motion`'s `work` (digging) and `carry` acts stand in.

## Next

- Hand-over with `strategy-map.md` (first task 3): forming squads from these people, and unloading `base.stock` at the barn.
- Saving the ranch with the campaign.
- Watch posts and walls in a raid, once `combat.md` reads cover from the grid.
