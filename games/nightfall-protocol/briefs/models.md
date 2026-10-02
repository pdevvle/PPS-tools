# Brief: models

Read `00-foundation.md` first, and the clothing schema doc linked there.

## Goal

Everything people see on the ground: the procedural survivors and raiders with their clothing and hair layers, weapons and kit, and the ink-faceted props (buildings, plants, bridge parts, vehicles, furniture for the base).

## Where it stands

- `mockups/base-figure.html` is the source of truth for **FigureKit**: lofted cross-section bodies, `genFace(seed,fem)` (about 30 face values plus `P.body` with 14 attributes), heritage profiles that skew features (blended at times), soft bust and glute lobes, shaped bare feet, joint blocks, `inkUp` outlines with state colours, shading styles (toon, painted, ink, ink faceted, two-tone, faceted, smooth; ink is the default).
- The kit is extracted by slicing `base-figure.html` from `const SKINS` to `const ui=` and from `// ---------- geometry` to `let figs`, wrapped as `const FigureKit=(()=>{ … return {figure, genFace, POSES, applyPose, mats, inkUp, STATES}; })();`. A current copy is `tools/stream/figure-kit.js`.
- Props: built in code in the sector runtimes (`SHAPES` in `tools/stream/stream-main.js`: saguaro, palo verde trunk and canopy, shrub, rock, reeds; buildings, walls, bridges, culverts, pools as batched geometry). Weapons are a placeholder box on the forearm (combat demo).
- `mockups/survivor-style.html` is an earlier Zomboid-style test; the original game has a large mannequin and prop catalog (`index.html`).

## Decisions (keep)

- Characters inked toon; props ink faceted (foundation).
- Hair and clothing are procedural layers, not part of the base figure. Heritage skews are generalisations to vary faces, applied as tendencies, never as fixed traits.
- Figures stay low-poly enough for a squad plus a few raiders on screen with streaming running.

## Interfaces

- `FigureKit.figure(fem, face)` returns `{root, body, hips, torso, head, sh, el, lg, kn, fem, FP}`; `applyPose(fig, joints)` with joint keys `bodyY torsoX torsoY headX shRx shRz elR shLx shLz elL lgR knR lgL knL` (shared with `animation.md`); `inkUp(root,{color,width,persp,creases})` returns the ink material so its colour can follow state; `STATES` holds the state colours.
- Combat attaches weapons to `fig.el[0]`; keep an attach point there or provide a better one and tell `combat.md`.

## Known gaps

- Clothing and hair layers (schema exists, not built).
- Raiders look like survivors with a red stroke; they need their own look (kit, masks, colours).
- Weapons and carried kit.
- Instanced props get outlines but no crease lines.
- Buildings are extruded footprints with hip or flat roofs; no doors, windows (except shop glass), porches, AC units, signs.
- Vehicles: cars were removed for clutter; a small set of wrecks and abandoned cars should return.
- Props for the base (beds, water tanks, gardens, workbenches, walls you build) once `building.md` names them.

## First tasks

1. Clothing layer from the schema: a few garments on the lofted body, coloured and worn.
2. Hair as a procedural layer.
3. Weapons and kit (rifle, shotgun, pistol, pack, canteen) with attach points.
4. A raider look.
5. Building facade detail kit (doors, windows, roof types, clutter) for `tactical-maps.md`.

## Out of scope

How figures move (`animation.md`), where props are placed (`tactical-maps.md`, `building.md`).
