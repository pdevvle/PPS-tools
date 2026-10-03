# Combat tools

Fighting inside procedurally generated buildings (task 7 in `briefs/combat-tasks.md`), with free placement: units stand at any point, not on a grid. Nothing here edits the interiors code. The interiors topic owns `tools/interiors/`, so this folder only reads it.

- `interiors-slice.js` cuts the generator and its renderer out of `tools/interiors/interiors.src.html` by marker comments, and inlines `kit.js` and `sites.json`. If the interiors page moves a marker, the build and the tests stop with a message.
- `space.js` turns a generated building into free space for a fight. The frame is the building's own, plus 12 m of yard all round.
  - **Geometry**: walls, doors, windows and counters (the generator's cell edges) become line segments. Furniture becomes boxes, and yard walls become thick segments.
  - **What each piece does**:

    | Piece | Cover | Sight and shots | Bodies |
    |---|---|---|---|
    | Wall | full | blocked | blocked |
    | Closed door | full | blocked | +1 m to open |
    | Open or broken door | none | pass | pass |
    | Window | half (the sill) | pass | +4 m to climb, +5 with intact glass |
    | Counter | half | pass | +3 m to vault |
    | Barricaded door, boarded window | full | blocked | blocked |
    | Furniture | from the kit | blocked only by full-cover pieces taller than 1.5 m (eye height) | blocked |

  - **Sight and shots** are rays. **Cover** is directional: the best cover the shot line crosses within 1.1 m of the target. So a unit beside a wall but shot along it is flanked.
  - **Bodies** have a 0.3 m radius.
  - **Movement** runs over a hidden 0.5 m cost field with 16 step directions, so a range is round to within a few percent. Doors, windows and counters are portals, so routes pass through the middle of every opening. Routes are pulled straight afterwards. `costTo` and `pathTo` work for any point, not just field nodes.
  - `snap` moves a click near cover to just behind it. `leans` lets a unit in cover step out sideways to see or shoot. `coverSpots` are points along every piece of cover, for the AI.
  - `posted()` gives the generator's people their roles: a sentry at a street-side window looking out, and the boss.
- `rules.js` holds the foundation's combat values as plain, seeded functions over points:
  - `odds` and `roll` for shots;
  - `lineOfFire`, which allows leaning out of cover;
  - `sees` for unaware raiders' sight cones;
  - `decide` for the raider AI, which scores cover spots and open floor in reach;
  - `simulate`, a fight with no rendering.
- `test-space.js` checks every wall, window and door on all test buildings under all four histories:
  - sight and shots through each piece, and the cover it gives;
  - routes never clip anything solid and enter or leave only through openings;
  - sight symmetry and determinism.

  Then hand checks on the Roadrunner: range is round, any point can be stood on, snapping, angled cover and a seeded replay. Run `node tools/combat/test-space.js`, or add `--quick` for the Roadrunner only.
- `demo-script.js` and `demo.src.html` are the playable page.
  - **Range**: smooth outlines, blue for one action and gold for a dash.
  - **Hover**: a ring where the unit would stand, the route there, and a marker toward each raider: tall gold for full cover, short gold for half, flat red for flanked.
  - **Sight**: drawn as fans cut by walls.
  - **Breach**: stack on the gold (door) and blue (window) rings, then breach with free shots.
  - **Fight**: XCOM turns, overwatch on the move, doors that open as units walk through, and glass that breaks.

  The interiors renderer draws the building, including its cutaway walls.

Build with `python3 tools/combat/build.py [artifact-fragment.html]`. It writes `mockups/combat-interior.html`. Published as https://claude.ai/artifact/Xm7C2fNtxDRpa57hQ2CYcW

The page exposes `window.__combat`, with `S.timeScale` for tests on slow software rendering.
