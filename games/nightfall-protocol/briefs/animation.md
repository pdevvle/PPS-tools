# Brief: animation

Read `00-foundation.md` first.

## Goal

Procedural motion for every figure: each person moves in their own way, actions vary within believable bounds, and idles never freeze, so a squad of generated people reads as individuals.

## Where it stands

- `mockups/procedural-motion.html` illustrates three layers: movement traits fixed per person by seed; actions rolled within per-joint bounds; idles with continuous smooth noise whose bands widen when wounded.
- `tools/motion/motion.js` is the shared module (see its README). The streaming page and the zoom page with the combat demonstration call `Motion.update` for every figure; neither runtime poses figures itself.
- **Feet:** a weight-bearing foot is pinned in the world. Hip, knee and ankle are solved to it, and feet step when walking, turning on the spot, changing stance or going round tight bends. The headless bench measures no planted-foot slip in any of these, and feet sit flat on slopes.
- **Weapons:** `Motion.arm(fig, 'rifle' | 'pistol')` gives a quick bolt-action rifle or service pistol. Each action has a hold per weapon (low carry, port arms, ready, aim, hug, slung or holstered), and both hands are solved to the grips. Firing kicks the weapon; the rifle works its bolt. Reloads are a stripper clip for the rifle and a magazine change with a slide rack for the pistol. The combat demo arms the squad and raiders with rifles and the raider boss with a pistol.
- **Hands:** jointed fingers (three joints each) and a two-joint thumb replace the mitten hand. They curl round grips with the index on the trigger, pinch, make fists, go limp, grab rungs and lie flat to push up.
- **Falls:** a verlet ragdoll shoved away from the shooter; the dropped weapon lies where it fell. Get-ups from the back or the front start from wherever the body lies.
- **Traversal:** `Motion.traverse` plays vault, ledge climb, ladder up, ladder down and drop clips that move the root themselves.
- Carry and dig are rough first versions for `building.md`.
- `mockups/motion-lab.html` (built by `tools/motion/build.sh`) is the test bench, published at https://claude.ai/artifact/BpzDxZh3j4PNgUSGaL93Sj:
  - a loop where four people walk, run and act with weapons, moods, hits, firing and falls;
  - an obstacle course run by two more.

## Decisions (keep)

- Motion is procedural, driven by the figure's seed, not keyframed clips. Traversal and get-ups are short procedural clips: key poses for the body, with world targets for hands and feet that the limbs are solved to. They start from a snapshot of the current pose.
- Wounded and panicked states should show in movement as well as in the ink.
- Runtimes say what a person is doing (`act`) and where the ground is; the module decides walking or running from how far the root really moved, so upper-body actions layer over the gait without extra states.
- A runtime that moves people faster than real time passes `compress`. The squad uses 2.6 m/s ÷ 1.39 m/s. Combat moves (4 m/s) use 1.4, so a tactical move reads as a run.
- The aim line comes from the weapon's hold and the look direction, never from noise or rolls; aim sway belongs to the Aim stat.
- Weapons are placed by the hold and the hands follow them (not the other way round), except a pistol carried at the side, which follows the swinging hand.

## Interfaces

- `FigureKit.applyPose(fig, joints)` with joint keys `bodyY torsoX torsoY headX shRx shRz elR shLx shLz elL lgR knR lgL knL`. On top of these, `Motion` sets shoulder and hip twist (rotation y and z) and neck yaw on the head. It adds two things to each figure the first time it sees it: ankle groups (`fig.an`, slipped between each knee and its foot meshes), `fig.hand` (the wrists), and jointed hands (`fig.fingers`, `fig.thumbs`), which replace the mitten mesh. **For `models.md`:** if FigureKit grows real ankles, fingers or a neck, `Motion` should use them instead.
- `Motion.update(fig, {act, mood, ground, slope, compress, look, lookAt, aimPitch}, dt)`, called after the runtime places `fig.root`. Acts: idle, walk, run, ready, aim, shoot, reload, crouch-walk, crouch, hunker, hit, carry, work, swim, fall, dead. Moods: calm, wounded, panicked.
- `Motion.arm(fig, kind)`; `Motion.WEAPONS[kind].grip` (grip points and hand axes in the weapon frame: origin at the trigger grip, +z down the barrel) is what a final weapon model from `models.md` needs to supply.
- `Motion.kick(fig, 'hit', k, {from:{x,z}})` and `Motion.kick(fig, 'recoil')`.
- `Motion.traverse(fig, {type:'vault'|'climb'|'ladder'|'descend'|'drop', x, z, yaw, height, depth, y}, state)`. While `Motion.busy(fig)` is true, a clip or the ragdoll owns `fig.root`; the runtime reads it back instead of moving it.
- Assembly order on a page: `figure-kit.js`, then `motion.js`, then the runtime.

## Known gaps

- Feet don't pick treads on stairs, so a foot can straddle a step edge.
- Traversal needs obstacle data: the tactical map doesn't mark walls, ledges or ladders yet (with `tactical-maps.md`). Combat doesn't use cover vaults yet (with `combat.md`).
- Weapons are stand-ins until `models.md` makes them. Nothing yet for crawling, throwing, melee or one-handed rifle use.
- Carry and dig are first versions; building (hammering, hauling, crafting at a bench) is still to do with `building.md`.

## Tasks

1. ~~Shared module for the streaming and combat runtimes.~~ Done.
2. ~~Seeded walk and run matching ground speed and slope; foot planting.~~ Done, with world-anchored feet and ankles.
3. ~~Combat set with grips.~~ Rifle and pistol holds, bolt and slide, reloads, hits from the shooter's side, ragdoll falls and get-ups are done. Reload is not wired into combat until it has ammunition, and panic still needs a trigger (both `combat.md`).
4. ~~Idle variety tied to state.~~ Done.
5. ~~Turning steps, vaults, climbs, ladders, drops.~~ Done in the lab. Next: mark obstacles on the tactical ground and let pathing use them (with `tactical-maps.md`).
6. Work motions for `building.md`: hammer, haul, crafting at a bench, sitting, sleeping.
7. Crawling and going prone; throwing.

## Out of scope

Figure geometry (`models.md`), what triggers an action (`combat.md`, `building.md`).
