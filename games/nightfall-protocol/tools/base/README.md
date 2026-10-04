# The base (the logistic layer)

Building's topic (`../../briefs/building.md`). `DESIGN.md` is the merged design. The prototype is `../../mockups/base.html`.

- `cut_site.py` cuts 760 × 500 m of the baked New River block (four sectors) into `../../data/base/ranch_site.json` (ODbL). The cut holds:
  - heights on the 4 m grid
  - the 2 m movement grid (kind and speed)
  - buildings, walls, plants, roads, washes and areas
  - the two suggested base points

  Rerun it when the bake changes.
- `ranch-core.js` holds the rules: founding a base, placing things, the grid writes, tasks in the shared shape, people walking to them, and water. It has no rendering. It uses `../people/people.js`, so it runs in the page and in Node.
- `ranch-main.js` is the page: the ground, buildings and plants in the streaming page's ink-faceted look, the built things, FigureKit people moved by `Motion`, the tools and the panels.
- `base-head.html` is the page's markup and style.
- `./build.sh` assembles `mockups/base.html` from the site data, `figure-kit.js`, `motion.js`, `people.js` and these files. It opens straight from disk. The published Artifact is the same page without its first two lines.
- `node test.js` checks the rules.
- `page-test.js` checks the page in Chromium:
  - places a tank and a wall line with the mouse;
  - builds a bunkhouse, a watch post and a gate, then runs four days and a night;
  - founds the base at the region home point and in open ground.

  Give it `THREE` (a path to three r128's `three.min.js`) and optionally a folder for screenshots.

## What the prototype does

- **Founding**: the base starts on the ranch lot. **Region home point** moves it to the other suggested point. **Found here…** puts the 140 m square wherever you click, as long as it fits on the cut. The clock carries on, and everything on the base starts over.
- **Placing**: pick a thing, then click the ground, or drag for a line of walls or barricades. R rotates. The ghost turns red where a thing can't go, and the tip says why: outside the base, on something, on blocked ground, in a wash (it floods), or a seep away from a wash.
- **Other orders**:
  - **Repair well** orders the hand pump.
  - **Take apart** removes a small outbuilding for 6 shelter. Its cells become open ground.
  - **Cancel** returns a planned thing's materials.
- **Grid**: the **Movement grid** view shows kinds, half cover (blue) and gates (brown). Paths go round blocked cells, and people standing on a cell that turns solid step off it.
- **People**: six `People` survivors, each with traits, skills, needs and mood.
  - Job choice is `People.score` over the tasks the base offers.
  - Build time is the catalogue's hours at Build 1, −15% per level above, and half speed for outdoor work 10–18.
  - The ink shows state: overwatch blue on watch, wounded red when dehydrated or hurt, panicked purple during a break.
- **Water**: each person carries a 2 L canteen and refills it at the house barrels or a tank. The body drinks from it through `People.step`. The seep fills 25 L a day for hauling, and the pump gives 15 L an hour, up to 60 L a day. A rain catcher adds 24 L per mm to the tanks (`Ranch.rainfall(mm)`); there is no rain model yet.
- **Clock**: speeds are 15×, 60× and 600× (600× is the map's 1×). Any stretch settles in half-minute steps; ten days take about 0.1 s in Node.

## Stand-ins until other topics deliver

- **`settlement.md`**: the stores and the starting stock, food handed out without rationing, and the seep and pump yields. Stockpile cells are not placed yet.
- **`interiors.md`**: inside the house. Indoor rest and sleep simply hide the figure, and the house floor counts as the ground.
- **`models.md` and `animation.md`**: work poses. `Motion`'s `work` (digging) and `carry` acts stand in.

## Next

- Hand-over with `strategy-map.md` (first task 3): forming squads from these people, and unloading at the store.
- Saving the base with the campaign, and wiring stores to `Settlement`.
- Raids, once `combat.md` reads cover from the grid.
