# Brief: interiors

Read `00-foundation.md` first.

## Goal

Procedural interiors for every building in the region. The squad should be able to walk into any house, shop or station and find a believable layout, furniture, cover and things worth taking. All of it is generated from the real footprint and what the building is, and it is the same every time you come back.

## Where it stands

Not started. Buildings today are closed shells: extruded OSM footprints with hip or flat roofs, and glass on long shop walls. The movement grid marks every footprint as impassable (`building`).

What there is to generate from, per building in the sector files (`tools/stream/bake.js`):
- `pts`: the real footprint, often not a rectangle;
- `type`: mostly `yes` in this area, sometimes `house`, `retail`, `commercial`;
- `levels` and `height` where mapped;
- `name`, `loot` and `what` for shops and services (pharmacy, convenience, fuel, restaurant and so on);
- a `house` flag for likely homes, set by the bake.

The Roadrunner store in the New River block and the houses around it are the first real test cases.

## Decisions (keep)

- Interiors are procedural, not hand-built. Each layout is seeded from the building's identity (block, sector and building index), so it never changes between visits.
- The layout follows what the building is: Arizona ranch houses (garage, living room, kitchen, bedrooms, bathrooms), corner stores, gas stations, pharmacies, restaurants, offices, schools, churches.
- Loot inside matches the site's loot category and what the place really was. A pharmacy has medicine on its shelves; a hardware store has tools.
- Visual style follows the foundation: furniture and fittings are ink-faceted props.
- **Office layouts (proposed in the mockup, from research).** Anthem's offices are 2-storey multi-tenant Class B blocks with suites of about 110–650 m², many of them medical, some left as unfinished shells. So big or multi-storey offices are split into a shared corridor of about 2 m along the middle of every wing, tied to the stair and lift cores, a street entrance and a back exit. Suites open onto that corridor, and each is an office suite, a clinic or a vacant shell. Private offices are about 3×3 to 3.6×3.6 m.
- **Fighting space (proposed in the mockup, from tactical level-design write-ups).**
  - Rooms carry a cover budget: big rooms keep clear floor between pieces of cover, and low cover is preferred to tall.
  - Rooms of 30 m² or more get a second door, so there is always another way in.
  - Corridors are wide enough to fight in.
  The values themselves belong to combat.
- **Cutaway as a building section (proposed in the mockup).** Walls between the camera and the point being worked on are cut to a 0.9 m stub, just under half-cover height, and slope back up at the edge of the cut. The cut faces are filled in a tone per build-up, so wall thickness and material read at a glance. A faint outline keeps the full wall height visible. Outside walls facing the camera are always cut.
- **Destructible walls (proposed in the mockup).** Every wall edge has a build-up: drywall, stucco over frame, concrete block or reinforced concrete. Thin walls give way to bullets, a sledge and grenades. Thick walls (block exteriors, shafts, walls between shops) stop rounds and need a breaching charge; a vault takes two. Damage runs cracked → holed (see and shoot through) → breached (walk through) and is kept in the change record. Combat sets the numbers.

## Decisions to make here (record them in this brief)

1. **Floor plans.** How to subdivide a footprint into rooms. Options include a room grammar per building type, or binary splits fitted to the footprint's main axis. Irregular footprints and L-shapes must work.
2. **Openings.**
   - The front door faces the nearest road; the garage door goes on the drive side.
   - Back doors open onto the yard walls.
   - Windows go on exterior walls, with sills and sizes by room type.
3. **Grid.** The 2 m outside movement grid is too coarse for rooms. The recommendation, to confirm or change:
   - a 1 m interior grid, with walls on cell edges in the XCOM style;
   - joined to the 2 m outside grid at the doors.
4. **Storeys.** Most buildings here are single storey. Decide how upper floors, stairs and roofs work for the few that aren't.
5. **Decay and history.** Layered on top of the plan:
   - looted or untouched;
   - barricaded;
   - broken glass and kicked-in doors;
   - someone living there now (a raider den, a survivor holdout).
   Generate it from a seed plus what the strategic layer knows about the place.
6. **When to generate.** Interiors are built only for buildings near the squad (for example within 50 m) and dropped when the squad leaves, like streamed sectors. What changes inside is kept as a small record of changes over the generated layout: opened doors, emptied containers, barricades built.

## Interfaces

- **Tactical maps** (`tactical-maps.md`):
  - Building records and exterior shells come from the bake and the streaming runtime.
  - The shell needs real openings where your doors and windows are, so agree a hook: the interior generator returns the openings, and the shell cuts them.
  - Interior cells must join the movement grid (`kindG`, `nodeSpeed`, `findPath`).
- **Models** (`models.md`): furniture and fittings kit (beds, sofas, tables, counters, shelving, fridges, toilets, desks, store aisles, coolers, fuel counters). Specify what you need; models builds the final pieces. Placeholder boxes are fine until then.
- **Combat** (`combat.md`):
  - Walls are full cover. Furniture is half cover, or full for heavy counters and fridges.
  - Doors open and close; windows can be shot through and climbed through.
  - Line of sight stops at walls.
  - Combat needs a cutaway: roofs and the walls nearest the camera hide when units are inside.
- **Strategy map** (`strategy-map.md`): a site's loot amount on the map and the containers inside should agree. Scavenging takes time per container.
- **Building** (`building.md`): the survivors' base is an interior too, edited by the player.

## Known constraints

- Footprints come from OSM as traced, sometimes with tiny jogs and slanted edges. Expect to simplify and square them before planning.
- Performance: a street of houses is a lot of geometry. Batch by material per building, keep fittings low-poly, and draw only what is near the squad.
- Testing uses software rendering (slow). Check frame rates in a real browser.

## First tasks

1. Build a mockup: interiors for three types on real footprints from the New River block — a ranch house, the Roadrunner store and one service building. Use a seed reroll button and a cutaway view with roofs off and near walls lowered.
2. Place doors and windows, and show the openings on the shell.
3. Join the interior grid to the streamed movement grid, so the squad can walk in at the front door and out of the back.
4. Map loot containers to the site's category and `what`.
5. Agree with combat on cover values and the cutaway, then make one fight happen inside the Roadrunner.

## Out of scope

- The streamed ground and exterior shells (`tactical-maps.md`)
- Final furniture models (`models.md`)
- Combat rules (`combat.md`)
- The base-building game (`building.md`)
