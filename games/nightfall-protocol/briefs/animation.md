# Brief: animation

Read `00-foundation.md` first.

## Goal

Procedural motion for every figure: each person moves in their own way, actions vary within believable bounds, and idles never freeze, so a squad of generated people reads as individuals.

## Where it stands

- `mockups/procedural-motion.html` illustrates three layers: movement traits fixed per person by seed (six people walking with their own stride, swing and pace); actions rolled within per-joint bounds (ghosted earlier rolls of a take-cover crouch); idles with continuous smooth noise and a live joint-angle trace whose bands widen when wounded.
- In the running prototypes, motion is still simple sine walks and fixed poses set in each runtime (`tools/stream/stream-main.js`, `tools/zoom/combat.js`): walk, swim, aim, hunker, flinch, recoil, fall.

## Decisions (keep)

- Motion is procedural, driven by the figure's seed, not keyframed clips.
- Wounded and panicked states should show in movement as well as in the ink.

## Interfaces

- `FigureKit.applyPose(fig, joints)` with joint keys `bodyY torsoX torsoY headX shRx shRz elR shLx shLz elL lgR knR lgL knL`, and `FigureKit.POSES` (`t`, `ready`, `stand`). If the joint set needs to grow (wrists, spine, ankles), coordinate with `models.md`.
- Runtimes call one update per figure per frame with what it is doing; the aim is a small API such as `Motion.update(fig, state, dt)` with states like walk, run, crouch-walk, swim, aim, shoot, reload, hunker, hit, fall, idle, carry, work.

## Known gaps

- No shared motion module: each runtime poses figures itself.
- Walk doesn't follow terrain (slopes, steps) or speed; feet slide.
- No transitions between states, no upper-body layering (aim while walking), no look-at.
- Base work motions (digging, carrying, building) will be needed by `building.md`.

## First tasks

1. Extract the motion layers from `procedural-motion.html` into a module usable by the streaming and combat runtimes.
2. Seeded walk and run that match the ground speed and slope; foot planting.
3. Combat set: aim, fire with recoil, reload, hunker, hit reactions, fall; with `combat.md`.
4. Idle variety tied to state (calm, wounded, panicked).

## Out of scope

Figure geometry (`models.md`), what triggers an action (`combat.md`, `building.md`).
