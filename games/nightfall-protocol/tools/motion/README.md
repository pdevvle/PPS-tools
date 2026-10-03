# Motion

`motion.js` is the shared procedural motion for FigureKit figures. The streaming page (`../stream`) and the zoom page with the combat demonstration (`../zoom`) both use it. `mockups/motion-lab.html` is its test bench, built by `./build.sh`.

## Using it

Place the figure first (`fig.root` position on the ground, yaw for its heading), then call once per frame:

```js
Motion.update(fig, {act:'ready', mood:'wounded', ground:(x,z)=>heightAt(x,z), compress:1.4}, dt);
Motion.kick(fig, 'hit');      // or 'recoil' when it fires
```

- `act` says what the body is doing: `idle`, `walk`, `run`, `ready`, `aim`, `shoot`, `reload`, `crouch-walk`, `crouch`, `hunker`, `hit`, `carry`, `work` (digging), `swim`, `fall` (or `dead`). Walking or running is not a separate order: it comes from how far the root really moved, so `ready`, `aim`, `carry` and `crouch-walk` keep their upper body while the legs walk.
- `mood` is `calm`, `wounded` or `panicked`. Wounds slump the posture, favour one leg (shorter stance, a dip onto it) and hold an arm in. Panic hunches the body, shortens the stride and makes the idle quicker and jumpier. Both widen the idle noise.
- `ground(x,z)` gives the ground height at a world point, so each foot finds its own footing (the bridge deck, steps, slopes). Without it, `slope` (rise per metre ahead) or flat ground is used.
- `compress` is how much faster than real time the runtime moves people. The gait shape follows the real speed and the cadence follows the speed on screen, so a squad moving at 2.6 m/s with `compress` 1.87 shows a 1.39 m/s walk played faster, with no foot sliding.
- `look` (a yaw relative to the body) or `lookAt` ({x,z}) turns the spine toward something.
- The figure's seed comes from `fig.seed` if set, otherwise from a hash of its face values, so the same person always moves the same way.

`Motion.update` returns the figure's motion record (`fig.motion`): `v` measured speed, `ph` gait phase, `gaitW` and `runW` blend weights, `stance` per leg, `out` the joints applied this frame.

## How it works

1. **Traits per person** (`Motion.traits(seed)`): stride, arm swing, slouch, bounce, arm width, stance width, fidget, the leg they rest on, head carriage.
2. **Rolls per action**: entering an action rolls every joint inside `Motion.BOUND`, scaled per action. Aiming rolls the arms less, because aim sway belongs to the Aim stat, not to cosmetics.
3. **Continuous noise**: smooth value noise on head, spine, shoulders and weight, damped while walking, widened by mood.
4. **Legs are solved, not posed.** The gait phase advances by distance covered divided by stride length. Stance feet move back at exactly body speed, so they stay put in the world. The swing foot lifts and goes ahead, and the heel rises before toe-off. The pelvis drops just enough for every foot to reach its ground, and a two-bone solve in the leg's plane gives hip and knee. Standing poses keep their designed foot placement, planted on the ground under each foot.

## Measured (headless, `tools/motion` bench over 10 s of walking)

- Planted-foot slip: 0 mm/s on flat ground, a 15% climb, a 20% descent and stairs; under 5 mm/s for the wounded gait and the idle weight shift.
- Stance foot on its ground: no sinking or floating, apart from the 4.5 cm heel lift before toe-off.
- In the lab the readout shows slip of a few cm/s on the loop's bends: the root turns in place, and the feet don't step round yet.

## Not yet

- **Ankles and neck yaw.** Feet stay rigid to the shin, so a planted foot tilts as the leg swings. Look-at can only turn the spine. Both need joints from `models.md`.
- **Hands on the weapon.** There is no grip solve yet; the gun hangs from the right forearm.
- Turning on the spot without stepping; stepping round tight bends.
- Vaults, climbs, ladders and getting up from a fall as its own motion (it is a blend for now).
- The runtime smooths the root's height, so on stairs the pelvis dips more than it should; per-foot ground handles the rest.
