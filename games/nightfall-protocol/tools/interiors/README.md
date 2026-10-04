# Interiors (draft)

The mockup for `briefs/interiors.md`, task 1: procedural interiors on real footprints from the New River block and the Anthem town centre (`data/sectors/sector_anthem.json`).

- `extract.py` cuts the test buildings out of the baked block (`mockups/streaming/block/`). It keeps each footprint, its identity, its tags and the roads and yard walls within 60 m, and writes `sites.json`. It also copies a shop's point of interest (`loot`, `what`) onto the building that sits on it. The bake does not do that yet.
- `interiors.src.html` holds the generator and the page. `kit.js` holds the prop kit: each prop is a builder that returns boxes in its own frame. The builders cover cabinets with doors and drawers, appliances, chairs and tables that vary with noise, cars, Southwest wall decor, and disorder (overturned furniture, hanging doors, pulled drawers, litter). `build.py` inlines `sites.json` and `kit.js` and writes `mockups/interiors.html`. Pass it a path to also write the Artifact fragment.

The generator runs in five seed streams from the building id (`newriver/2_2/0`, plus `#n` when rerolled):

1. program
2. plan
3. openings
4. furniture
5. history and loot

Changing the history never moves a wall.

Steps:

0. Split strip malls into tenant units. Each point of interest inside a footprint becomes a tenant. Each cell goes to the nearest tenant, with distance counted mostly along the frontage, so party walls run back from the street. Each unit is then planned, opened and loot-stocked by its own type.
1. Square the footprint onto its main axis and rasterise it to 1 m cells.
2. Split the cells into rooms by binary partition, following a room grammar per building type. A house's bedroom wing is planned along a hall spine instead.
3. Place doors from the hub room outward by neighbour preference. Place the front, garage and back doors from the nearest road and drive. Place windows by room type.
4. Place furniture against walls or free-standing, keeping every door and container reachable.
5. Layer the history on top, then deal the site's loot amount across the unsearched containers.

Building types:

- Ranch house, restaurant (bar, pizza, Asian and Mexican variants change the kitchen and the decor)
- Fast food and ice cream, coffee shop, bank (teller line, vault, safe deposit boxes), offices (cubicles, conference room, server closet)
- Corner store, gas station store, pharmacy, supermarket, hardware store, small shops (jeweller, dry cleaner, postal counter)
- Auto service (bays with lifts), hair salon, clinic (dental chairs or exam tables), fuel canopy

Multi-storey buildings: `site.levels` gives the count. Cores are 3 × 6 m switchback stairs and a 3 × 3 m lift, chosen once by `coresFor` and shared by every floor. Each floor is planned, opened, furnished and stocked on its own seed stream (`|f1`, `|f2`…). The view shows one floor at a time, draws the floors below as shells, and has a roof level with plant, bulkheads and, for holdouts and dens, a lookout camp.

`fetch_osm.py` caches buildings outside the baked sectors from the OSM API into `osm_extra.json`. Overpass was unreachable from the build container. 42015 North Venture Drive, the office block across the wash west of the Safeway strip, comes from there. OSM tags it `building=house` with no level count, so the mockup builds it as three storeys of offices.

Physics: a "Click does" control switches clicks between searching, throwing a grenade and overturning furniture.
- A grenade (4.5 m) runs cannon.js (cdnjs, 0.6.2) on the props in range, with walls, untouched furniture and the floor as static colliders. Heavy fittings in `STATIC_PROPS` (kit.js) stay put. Each chair is its own piece, so dining sets come apart. The blast breaks windows within reach and blows nearby doors.
- Overturning is scripted, not simulated. Props in `FLIP_PROPS` tip onto the edge away from the camera. A table becomes a low wall giving half cover; tall things fall flat. The chairs stay where they were.
- Either way the outcome goes into the change record as a pose per piece, the cells the prop now blocks and the cover it gives (`moved`), plus scorch marks (`blasts`) and broken windows (`windows`). Reloads redraw from the record, so physics never has to replay the same way twice.
- Walls are destructible. Each wall edge gets a build-up when it is generated (`WALLMAT`, `assignWallMats`):
  - drywall partitions inside;
  - stucco over wood frame, or concrete block, for house exteriors;
  - block for shop and office exteriors, for stair and lift shafts, and between shops in a strip;
  - framed exteriors on upper office floors;
  - reinforced concrete round a vault.
  The build-up sets the drawn thickness and what each tool does:
  - **Shoot:** fires a round level along the view. Drywall and frame let it through; block and concrete stop it.
  - **Sledgehammer:** opens drywall in a blow or two and frame in a few; block only chips.
  - **Breaching charge:** opens any wall (a vault takes two) and throws whatever stands close.
  - **Grenade:** cracks, holes or breaches thin walls near it; a solid wall in between shields what is behind.
  Damage climbs from cracked to holed (see and shoot through) to breached (walk through), and is kept in the change record as `walls` (state, hole position, bullet holes). The geometry, gaps and rubble are seeded from the edge, so reloads redraw them the same. The values are placeholders for combat to set.

Rebuild after editing: `python3 tools/interiors/build.py`.


Rendering: the scene draws at about twice the screen's pixels (multisampled where WebGL 2 allows) and is filtered down ("Smoothing" toggles it). Floor and wall patterns are carried by colour at half a metre or more, with no hairline grout or plank gaps. Ink outlines only pieces with some body; seams where two boxes abut are dropped, and faces sit a hair behind their ink so lines don't flicker.