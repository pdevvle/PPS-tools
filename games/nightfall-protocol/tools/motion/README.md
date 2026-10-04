# Motion

`motion.js` is the shared procedural motion for FigureKit figures. The streaming page (`../stream`) and the zoom page with the combat demonstration (`../zoom`) both use it. `mockups/motion-lab.html` is its test bench, built by `./build.sh`: a loop over a ramp and stairs with four armed people, and an obstacle course with two more.

## Using it

Place the figure first (`fig.root` position on the ground, yaw for its heading), then call once per frame:

```js
Motion.arm(fig, 'rifle');                 // or 'pistol', or null to disarm; once, when the figure is made
Motion.update(fig, {act:'ready', mood:'wounded', ground:(x,z)=>heightAt(x,z), compress:1.4}, dt);
Motion.kick(fig, 'hit', 1, {from:{x,z}}); // flinch away from the shooter; a hit before a fall shoves the ragdoll
Motion.kick(fig, 'recoil');               // fire: the weapon kicks, a bolt-action rifle then works its bolt
Motion.traverse(fig, {type:'vault', x, z, yaw, height, depth}, state);   // see Traversal
if(Motion.busy(fig)) { /* a clip or ragdoll owns the root: read fig.root back instead of moving it */ }
```

- `act` says what the body is doing: `idle`, `walk`, `run`, `ready`, `aim`, `shoot`, `reload`, `crouch-walk`, `crouch`, `hunker`, `hit`, `carry`, `work` (digging), `swim`, `fall`, `dead`. Walking or running isn't a separate order. It comes from how far the root really moved, so `ready`, `aim`, `carry` and `crouch-walk` keep their upper body while the legs walk.
- `mood` is `calm`, `wounded` or `panicked`.
- `ground(x,z)` gives the ground height at a world point. Each foot, the ragdoll and every clip use it. Without it, `slope` or flat ground is used.
- `compress` is how much faster than real time the runtime moves people. The gait shape follows the real speed and the cadence the shown speed.
- `look` (a yaw relative to the body) or `lookAt` ({x,z}) turns the spine and the neck, and the aim follows it. `aimPitch` tips the aim up or down.
- The figure's seed comes from `fig.seed` if set, otherwise from a hash of its face values.

## Legs and feet

- A foot that bears weight is pinned to its spot in the world. Hip (three axes), knee and the new ankle are solved to reach it, with the knee pointing forward.
- Walking swaps feet by the gait phase, which moves by the distance covered divided by the stride. Standing still, a foot steps when the stance wants it elsewhere or the body has turned 30° away from it. That gives turning on the spot, small shuffles and changes of stance, and no foot slides round tight bends.
- **Pelvis.** The pelvis moves three ways while walking, all sized per person:
  - it shifts over the standing leg (sway, 14–32 mm each way);
  - it drops on the swinging side (tilt, 2.5–6.5°, about 30% more for women);
  - it turns forward with the swinging leg (twist, 3–7.5°).

  The chest turns against the twist and levels against the tilt, so shoulders and head stay steady. Knees, and so feet, point the way each foot landed, whatever the pelvis is doing. Standing, the pelvis rests on one hip (the favoured one, or away from a wound) and drifts. Measured at 1.4 m/s: sway 45 mm, tilt 9°, twist 11° peak to peak; shoulders tilt only 2°.
- **Gait height.** Only feet bearing weight hold the pelvis down; a swinging foot bends its knee to fit and counts only as it lands. The back foot rolls onto the ball of the foot before push-off (the ankle pivots round the ball, so the ball stays put), and the front foot lands heel first (pivoting round the heel). The foot lands slightly under the body, and the stance leg is nearly straight (99.3% of its length). Measured pelvis bob over four people:

| Gait | Pelvis bob | Knee at mid-stance |
|---|---|---|
| Walk at 1.4 m/s | 36 mm (was 74) | 15° (was 23°) |
| Stroll at 0.8 m/s | 18 mm (was 48) | 15° (was 23°) |
| Squad pace on the streaming page | 40 mm (was 80) | 15° (was 23°) |
| Run at 3.4 m/s | 58 mm (was 82) | |

  The contact point (heel while landing, ball while rolling off) stays within 1 mm/s on flat ground and slopes.
- Ankles keep each planted foot flat on its own ground (capped at 23° where a foot straddles a step). The heel lifts before toe-off and the toes come up through the swing.
- **Hands.** FigureKit's hand is one mitten mesh and a thumb. The first time `Motion` sees a figure, it swaps each for a palm, four fingers of three joints each and a two-joint thumb. They are sized from the mitten, use the same skin and keep the ink outline.
  - Joints: `fig.fingers[hand][finger][joint]` (index to little, base to tip) and `fig.thumbs[hand][joint]`. `Motion.setHand(fig, i, {curl, index, thumb, spread})` poses one hand directly.
  - Fingers wrap round a weapon grip, with the index finger on the trigger and the palm turned to the grip.
  - They pinch for a bolt, clip or magazine, hold a load or a tool, and make fists in panic.
  - They go limp in a fall, grab rungs and edges when climbing, and lie flat when pushing up off the ground. Otherwise they keep a loose, slowly changing curl.
- **Grasping by contact.** On a weapon, each hand is seated and its fingers close until they touch.
  - The palm is placed on the grip's real surface, found by probing from the grip point along the palm's direction.
  - Each finger and the thumb close from the knuckle out. With the joints beyond it straight, a joint turns until one of its segments touches a part of the weapon, then the next joint closes.
  - The colliders are the weapon's own parts (each mesh's box), so a new model brings its own.
  - The thumb can also swing sideways to clear the grip.
  - A carried pistol is slid along the palm's normal until its grip rests on the palm.
  - A hand's result is reused while it sits the same way on the weapon (within 1.5 mm) and asks for the same curl.
  - `Motion.grasp=false` turns contact off, leaving fixed curls.
  - Measured with all five digits touching in every hold (rifle aim, ready and low; pistol aim and carried): worst sink 0.5–3.7 mm against 14–30 mm with fixed curls, fingertips within 0–6 mm of the surface. The cost is about 0.1 ms per armed figure per frame.
- **Rifle stance.** Rifle aim, ready and reload are bladed: the body turns about 45° to the right so the left hand reaches the fore-end, and the neck turns the head back to the target.
- **Ankle joint.** FigureKit has no ankle. `Motion` slips a group between each knee and its foot meshes (`fig.an`) the first time it sees a figure. It also sets `fig.hand` (the wrist groups) and neck yaw on `fig.head`.

## Variation

Every animation draws from ranges, so nothing plays the same way twice:

- **Per person:** traits from the seed.
- **Per action:** the pose roll.
- **Per stride:** stride length, foot lift, sway, tilt and twist follow smooth noise over the stride count. How much they vary is itself a trait (`vary`).
- **Per clip:** vaults, climbs, drops and get-ups get a tempo (±12%) and nudged in-between keys. Hands on an edge and feet on the ground only move along the surface. Ladders roll their climbing speed, which rung the hands start on, the lean and the top-out.
- **Weapons:** cycles (bolt, reloads) roll their tempo; hits and recoil roll their size and side.
- **Steps:** turning steps roll their timing and lift.
- **Dig:** each stroke is rolled afresh (see below).

## Dig

`work` digs with a D-handle spade (built when needed). Both hands are solved onto it with the same grasp-by-contact as weapons, and the weapon is slung. Each stroke is rolled:

1. Drive the blade in (13–21 cm deep).
2. On most strokes, step onto the tread with the right foot and push.
3. Lever back.
4. Lift, turn left and throw the soil (it flies and lands).
5. Come back.

Duration, spot, depth, lever, throw distance and height, and the blade flip all vary.

## Weapons

`Motion.arm(fig, kind)` builds a quick inked model, parented to the root:

- **Bolt-action rifle** (Mauser pattern, 1.1 m), with a working bolt and a stripper clip for reloads.
- **Pistol** (service automatic, 0.21 m), with a working slide and a magazine.

Each action picks a hold for each weapon:

| Hold | Rifle | Pistol |
|---|---|---|
| relaxed | low carry, both hands, muzzle down and across | in the right hand, arm swinging |
| running | port arms | in the hand |
| ready | low ready, butt in the shoulder | compressed ready |
| aim | butt in the shoulder pocket, cheek down, along the look | two hands, arms out, along the look |
| hunker | hugged upright | close to the chest |
| reload | canted down: bolt open, clip from the pouch, thumbed in, bolt closed | magazine out, new one from the belt, slide racked |
| carry, dig, swim, clips | slung on the back | holstered on the hip |

The weapon is smoothed between holds. The arms are solved so the wrist sits behind each grip, and the wrist turns the hand along the grip. The aim line comes from the hold, not from the noise layers, so idle noise never moves the aim. Recoil kicks the weapon back and up (the pistol flips more). The bolt cycle and reloads are hand timelines, and the bolt or slide follows the hand.

## Drawing and stowing

Moving a weapon between the hands and its stowed place plays a transition instead of a glide. It starts whenever the hold changes between in-hand and stowed: an action that slings or holsters (carry, dig, swim), or `holster:true` in the state.

- **Pistol, holster:** the support hand lets go. The pistol comes back to the body, muzzle down over the holster mouth, slides in, and the hand opens and drops.
- **Pistol, draw:** the hand reaches to the holster and closes on the grip, lifts the pistol straight out, turns the muzzle forward at the chest, and pushes out as the support hand joins.
- **Rifle, sling:** the support hand lets go. The rifle comes up vertical in front of the right shoulder, the hand slides up to the fore-end, swings it over the shoulder onto the back, and lets go.
- **Rifle, unsling:** reach over the shoulder for the fore-end, swing it forward, the left hand catches the fore-end, the right slides down to the grip.

The weapon's path is keyed on the moving body, so it can be done while walking. A hand not on the weapon hangs and swings until it takes hold. Each swap rolls its tempo (±15%) and a few centimetres of its path. About 45% of pistol swaps glance down at the holster.

## Falls and get-ups

- `fall` or `dead` starts a ragdoll of 19 verlet particles (trunk, head, limbs, toes, and the weapon's grip and muzzle) held by distance constraints. It collides with `ground` and has friction.
- It starts with the body's own velocity plus the shove of the last hit, away from the shooter, upper body most. The knees buckle forward.
- The skeleton follows: the trunk sets the body, the limbs are solved to their particles, and the dropped weapon lies where it fell.
- When the act leaves `fall`, the figure gets up from wherever it lies:
  - from the back: sit up, tuck a foot in, push off with a hand, stand;
  - from the front: hands and knees, a foot forward, stand.
- The root moves to where the figure stands up. `dead` stays down.

## Traversal

`Motion.traverse(fig, spec, state)` starts a clip, and the clip moves the root itself. The figure should stand about 0.4 m before the face, facing `yaw`. Spec `x,z` is the base of the face, and `height` is the top.

- `vault`: a low wall up to about 1.2 m (`depth` its thickness). One hand on top, legs tucked to the side, a crouched landing.
- `climb`: a ledge of 1–2.2 m. Reach, hang with the feet on the wall, mantle, then crouch and stand on top.
- `ladder`: rungs every 0.3 m. Hands on the rails and feet on the rungs move in diagonal pairs, then over the top onto the floor.
- `descend`: the ladder climb played backward. Stand on top facing away from the edge; the course turns the figure on the spot first.
- `drop`: step off an edge of `height` (pass `y` for the ground below). A fall timed by gravity, then a crouched landing.

Every clip starts from a snapshot of the current pose, so nothing pops. The weapon slings for the climb.

## Measured (headless bench, 10 s each)

- Planted-foot slip: 0 mm/s walking and running on flat ground, a 15% climb, a 20% descent and stairs, round a 1.5 m circle, and turning on the spot (26 steps in 10 s).
- Feet flat on their ground within 2.5° (stairs aside, where the heel and toe straddle a step edge).
- Hands on grips: 0 mm from the solved wrist position. The limb solver is exact for any reachable target (2,000 random tests, error below 1e-14).

## Not yet

- Feet don't choose treads on stairs; a foot can straddle a step edge.
- No grip-swapping or one-handed rifle use; no throwing, melee or crawling.
- Traversal needs the runtime to say where the obstacles are. The tactical map doesn't mark walls, ledges or ladders yet (`tactical-maps.md`).
- The rifle and pistol are stand-ins until `models.md` makes weapon models; their grips are the interface (`Motion.WEAPONS[kind].grip`).
