# Combat tools

Fighting inside procedurally generated buildings (task 7 in `briefs/combat-tasks.md`). Nothing here edits the interiors code. The interiors topic owns `tools/interiors/`, so this folder only reads it.

- `interiors-slice.js` cuts the generator and its renderer out of `tools/interiors/interiors.src.html` by marker comments, and inlines `kit.js` and `sites.json`. If the interiors page moves a marker, the build and the tests stop with a message.
- `interior-world.js` turns a generated building into a combat world.
  - **Grid**: 1 m cells in the building's own frame, plus 12 m of yard all round.
  - **Edges** (walls, doors, windows) set movement, sight and cover:
    - wall: full cover; it stops sight and shots;
    - closed door: full cover and stops sight, costs +1 m to open;
    - open or broken door: no cover, sight and shots pass;
    - barricaded door: closed to movement and sight;
    - window: half cover (the sill), sight passes, climbing through costs +4 m (+5 with intact glass);
    - boarded window: closed to movement and sight.
  - **Furniture**: each item's cover comes from the kit. Items with full cover taller than 1.5 m (eye height) block sight.
  - **Diagonal steps** only where there's no door frame to clip.
  - `posted()` gives the generator's people their roles: a sentry at a street-side window looking out, and the boss.
- `rules.js` holds the foundation's combat values as plain, seeded functions:
  - `odds` and `roll` for shots;
  - `reach`, a Dijkstra search in effective metres;
  - `peeks` and `lineOfFire`: stepping out from full cover, never through a wall;
  - `sees` for unaware raiders' sight cones;
  - `decide` for the raider AI;
  - `simulate`, a fight with no rendering.
- `test-interior.js` checks every wall, window and door on all 16 test buildings under all four histories, plus hand checks on the Roadrunner, and replays a seeded fight. Run `node tools/combat/test-interior.js`, and add `--map` for an ASCII plan of the Roadrunner den showing the sentry's sight.
- `demo.src.html` is the playable page.
  - **Concealed**: raiders' sight is drawn on the floor in red. Turning heads and noise (doors 4 m, glass 14 m) can give you away.
  - **Breach**: stack at doors and windows, then breach. Each breacher gets one free shot, at −10 through a window.
  - **Fight**: XCOM turns on the 1 m grid. Cover shields show on hover, closed doors open as you walk through, and shots break glass.
  - **Clock**: 5 game minutes pass per character turn.

  The interiors renderer draws the building, including its cutaway walls.

Build with `python3 tools/combat/build.py [artifact-fragment.html]`. It writes `mockups/combat-interior.html`. Published as https://claude.ai/artifact/Xm7C2fNtxDRpa57hQ2CYcW

The page exposes `window.__combat`, with `S.timeScale` for tests on slow software rendering.
