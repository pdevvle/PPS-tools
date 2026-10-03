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

Rebuild after editing: `python3 tools/interiors/build.py`.
