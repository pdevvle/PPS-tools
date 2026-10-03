# Brief: animation

Read `00-foundation.md` first.

## Goal

Procedural motion for every figure: each person moves in their own way, actions vary within believable bounds, and idles never freeze, so a squad of generated people reads as individuals.

## Where it stands

- `mockups/procedural-motion.html` illustrates three layers: movement traits fixed per person by seed (six people walking with their own stride, swing and pace); actions rolled within per-joint bounds (ghosted earlier rolls of a take-cover crouch); idles with continuous smooth noise and a live joint-angle trace whose bands widen when wounded.
- `tools/motion/motion.js` is the shared module (see its README). The streaming page and the zoom page with the combat demonstration both call `Motion.update` for every figure; neither runtime poses figures itself any more.
- Walk and run are seeded and solved: the gait follows the distance actually covered, stance feet stay planted, and each foot finds its own ground on slopes, steps and bridge decks. The headless bench measures no planted-foot slip.
- The combat set (ready, aim, reload, hunker, hit, recoil, fall) and idles that change with mood (calm, wounded, panicked) are in the module. Carry and dig are rough first versions for `building.md`.
- `mockups/motion-lab.html` (built by `tools/motion/build.sh`) is the test bench: four people on a loop over a ramp and stairs, with speed, action, mood and events. Published: https://claude.ai/artifact/BpzDxZh3j4PNgUSGaL93Sj

## Decisions (keep)

- Motion is procedural, driven by the figure's seed, not keyframed clips.
- Wounded and panicked states should show in movement as well as in the ink.
- Runtimes say what a person is doing (`act`) and where the ground is; the module decides walking or running from how far the root really moved, so upper-body actions layer over the gait without extra states.
- A runtime that moves people faster than real time passes `compress`: gait shape comes from the real speed, cadence from the shown speed, and feet don't slide. The squad uses 2.6 m/s ÷ 1.39 m/s; combat moves (4 m/s) use 1.4, so a tactical move reads as a run.
- Rolls never move the aim: steady actions roll the arms at 30%, since aim sway belongs to the Aim stat.

## Interfaces

- `FigureKit.applyPose(fig, joints)` with joint keys `bodyY torsoX torsoY headX shRx shRz elR shLx shLz elL lgR knR lgL knL`, and `FigureKit.POSES` (`t`, `ready`, `stand`). If the joint set needs to grow (wrists, spine, ankles), coordinate with `models.md`.
- `Motion.update(fig, {act, mood, ground, slope, compress, look, lookAt}, dt)`, called after the runtime places `fig.root`. Acts: idle, walk, run, ready, aim, shoot, reload, crouch-walk, crouch, hunker, hit, carry, work, swim, fall/dead. Moods: calm, wounded, panicked.
- `Motion.kick(fig, 'hit' | 'recoil', strength)` for one-off impulses; `Motion.traits(seed)`; `fig.seed` overrides the seed hashed from the face.
- Falls rotate `fig.body` (not `fig.root`), so runtimes keep owning the root's position and heading.
- Assembly order on a page: `figure-kit.js`, then `motion.js`, then the runtime.

## Known gaps

- **Needs joints from `models.md`**: ankles (a planted foot tilts with the shin) and neck yaw (look-at can only turn the spine). Wrists would help the grip.
- Hands are not solved to the weapon grip yet.
- No stepping when turning on the spot or round tight bends, so feet slip a little there.
- No vaults, climbs or a proper get-up; recovering from a fall is a blend.
- Carry and dig are first versions; building (hammering, hauling, crafting at a bench) is still to do with `building.md`.

## First tasks

1. ~~Extract the motion layers into a module used by the streaming and combat runtimes.~~ Done: `tools/motion/motion.js`.
2. ~~Seeded walk and run that match ground speed and slope; foot planting.~~ Done.
3. Combat set with `combat.md`: aim, fire with recoil, reload, hunker, hit reactions and fall are in. Next: a grip solve for both hands, reload wired into combat once it has ammunition, and directional hit reactions from the shooter's side.
4. ~~Idle variety tied to state.~~ Done for calm, wounded and panicked; combat feeds wounded from HP. Panic needs a trigger from `combat.md`.

## Next tasks

1. With `models.md`: ankle and neck-yaw joints; then foot pitch to the ground and a real look-at.
2. Turning steps and stepping round tight bends.
3. Work motions for `building.md`: hammer, haul, crafting at a bench, sitting, sleeping.

## Out of scope

Figure geometry (`models.md`), what triggers an action (`combat.md`, `building.md`).
