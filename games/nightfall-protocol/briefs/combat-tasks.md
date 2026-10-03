# Combat: task drafts

Working drafts for the first tasks in `combat.md`, plus one more task (7) for fighting inside buildings. Read `00-foundation.md` and `combat.md` first. Nothing here is decided until it moves into the "Decisions" section of `combat.md`.

## What already exists

- `tools/zoom/combat.js` (190 lines) is spliced into `stream-z.js` and uses that file's scope freely: `GN`, `NS`, `HALF`, `NK`, `IDX`, `sectors`, `key`, `mat`, `mtx`, `tmp`, `say`, `follow`, `squadInfo`, `W`, `H` and `TAU`, on top of the documented interface. Every roll uses `Math.random`.
- `tools/interiors/` is much further along than `interiors.md` says (that brief still reads "Not started"). It already has:
  - a 1 m grid in each building's own frame (`M.toL`/`M.toW`, rotated to the footprint's main axis);
  - walls stored on cell edges (`O.edges`, keys from `edgeKey`), plus doors and windows;
  - door states `closed | open | broken | barricaded` and window states `intact | broken | boarded`;
  - a `cover` value (`none | half | full`) and a height on every furniture item;
  - four histories: `untouched | looted | holdout | den`;
  - a list of people from `decay()`: `{c, side:'raider'|'survivor', boss}`. A den holds 3–5 raiders and a holdout 2–4 survivors.
  
  In short, interiors already generates encounters. Nothing joins it to the streamed ground or to combat yet.
- The original game (`index.html`) has the classes (Ranger, Sharpshooter, Grenadier, Specialist), weapon profiles (`short | mid | long | melee`, with ammo and crit numbers), concealment, grenades that destroy cover, and first-person overwatch.
- Task 6's rule (5 game minutes per character turn) is written into the foundation (commit `060a587`), but the code doesn't do it yet.

## Suggested order

```
1 module ──┬─> 2 cutaway ──────────────┐
           ├─> 3 encounters ─┬─> 7 interiors (needs interiors.md task 3)
           ├─> 4 classes ────┤
           ├─> 5 wounds      │
           └─> 6 clock       └─> (strategy-map task 4: roaming threats)
```

Task 1 comes first because every other task gets easier with a clear interface. Tasks 2–6 can run in any order. Task 7 is the biggest. Its groundwork (7a, 7b) can start as soon as task 1 lands, but walking in through a door needs `interiors.md` task 3: joining its grid to the streamed grid.

---

## 1. Combat as its own module

**Goal.** Move combat out of the splice. Rules become plain functions over plain data, which the foundation calls "portable logic". Rendering and input go in a separate layer.

**Shape.**

- `tools/combat/rules.js`: pure and deterministic from a seed, with no three.js and no DOM.
  - `odds(attacker, target, world, opts)`, `rollShot(odds, rng)`, `reach(unit, world)`, `coverFrom(node, fromX, fromZ, world)`, `los(a, b, world)`.
  - Raider decisions: `chooseAction(unit, state, world, rng)` returns an action object, so the AI can be tested without rendering.
  - A seeded RNG (the same mulberry/FNV pair as `interiors.src.html`), keyed by encounter id and round.
- `tools/combat/world.js` is the **world adapter**: the only part that knows about the tactical runtime. It turns a node id into `{x, y, z}` and gives a node's neighbours with their costs, a node's cover, sight between two points and a node's height. Today the only node kind is a 2 m ground cell. Task 7 adds interior cells and deck cells behind the same interface (see 7a).
- `tools/combat/view.js` holds the figures, overlays, popups, tracers, banner, action bar and camera goal. It does today's job using the adapter.
- `CB` keeps its hooks (`frame`, `click`, `hover`, `onBuilt`, `onDropped`, `active`, `prompt`) so that `stream-z.js` changes by only a line or two. Create it with `createCombat(rt)`, passing an explicit runtime object instead of relying on shared scope: `{cellOf, kindG, NK, nodeSpeed, nearestPassable, heightAt, deckAt, GN, NS, HALF, scene, cam, target, figs, squad, stage, say, FigureKit, IDX, sectors}`.

**Done when.**

- The zoom page plays exactly as it does today.
- `zoom-head` assembly lists `tools/combat/*.js` and no longer splices anything.
- A Node test runs `rules.js` without a browser. It checks the foundation's odds table (cover, height, distance, overwatch, first strike) and checks that a seeded fight replays identically.

**Risk.** Shared-scope names leak in quietly. Grep for every free identifier before cutting.

---

## 2. Camera cutaway

**Goal.** You can always see the focused unit, whether it's under a bridge deck, under a roof or inside a building.

**Approach.**

- Each frame during a fight, cast from the camera to the focused unit's chest (and to the cursor's target cell). Every deck, roof or wall mesh that the ray crosses *above or in front of* the focus fades to about 15% opacity with depth-write off. When the focus moves, the mesh fades back in over 0.3 s.
- **Decks**: use `deckAt` and the bridge's index. Hide the deck span within 12 m of the focus, not the whole bridge.
- **Interiors**: use the interiors mockup's cutaway mode. When the focus is inside a footprint, take the roof off the whole building. Walls whose outward normal faces the camera drop to 1 m (the "lowered" look), so furniture cover still reads.
- **Units behind solid things**: draw their ink stroke through walls as a dashed silhouette (a second ink pass with `depthFunc` greater). That way an enemy you know about but can't see doesn't vanish.
- **Small screens**: the action bar collapses to a single row with an expand chevron below about 700 px of height (a known gap in `combat.md`).

**Needs from others.** `tactical-maps.md` tags deck and roof meshes per bridge and building (`userData.cutaway = {kind, id}`). `interiors.md` exposes a per-building wall group split by facing.

**Done when.** A fight under the New River bridge shows every unit from the default camera, and at most 4 extra draw calls are added while a cutaway is active.

---

## 3. Encounter data

**Goal.** Encounters are data, not code. This one format covers encounters placed by hand, encounters coming from the strategy map, and encounters generated inside buildings.

**Format (draft, to agree with `strategy-map.md`):**

```json
{
  "id": "newriver/roadrunner-den",
  "seed": "newriver/roadrunner-den#0",
  "where": { "block": "newriver", "x": 412.0, "z": -96.0, "building": "newriver/2_2/0" },
  "faction": "raiders",
  "attitude": "hostile",
  "alert": "unaware",
  "pods": [
    { "id": "camp", "room": "rdining", "stance": "idle",
      "units": [ { "kind": "raider" }, { "kind": "raider" }, { "kind": "raider_boss" } ] },
    { "id": "sentry", "edge": "window:front", "stance": "watch",
      "units": [ { "kind": "raider" } ] }
  ],
  "patrols": [
    { "pod": "road", "route": [[380,-120],[455,-60]], "loop": true, "pause": 20,
      "units": [ { "kind": "raider" }, { "kind": "raider" } ] }
  ],
  "reinforce": { "trigger": "noise", "from": "patrol:road", "afterRounds": 1 },
  "retreat": { "below": 0.5, "to": "door:back" },
  "source": "placed"
}
```

- **`where`**: outdoor positions are in block-frame metres. Indoors, pods name a `room` kind or an opening (`door:front`, `window:front`), and positions come from the interior generator (7d).
- **`alert`**: one of `unaware | suspicious | alert`.
  - *Unaware*: cones are drawn, idle animations play, and the squad can get a first strike.
  - *Suspicious*: something was heard. One unit walks to investigate, the rest face the noise, and cones widen to 160°. A first strike is still possible but costs −10 aim.
  - *Alert*: no first strike, and pods start in cover.
- **`attitude`**: one of `hostile | wary | friendly`. Wary units don't open fire. Their trigger is a "hail" prompt instead of combat (see 7f).
- **Unit kinds** (`tools/combat/units.json`): `raider`, `raider_boss`, `survivor`, `scavenger`. Each kind sets hp, aim, weapon, sight and ink. Today's numbers come from the foundation.
- **Noise** (new, needed by 7). Each event has a radius in metres:

  | Event | Radius |
  |---|---|
  | Running | 6 |
  | Opening a door | 4 |
  | Kicking a door | 20 |
  | Breaking glass | 14 |
  | Gunshot | 60 |
  | Explosion | 120 |

  Each wall between the source and the listener halves the radius. Each closed door takes off a quarter. A pod inside the radius goes from unaware to suspicious, or from suspicious to alert.
- **Lifecycle**: the encounter is *armed* when its sector is built, *dropped* when the sector drops (unless a fight is on), and *resolved* when it is `cleared | fled | avoided`. Resolutions are written back to the campaign state (strategy-map task 1).

**Three placed encounters in the New River block:**

1. **Bridge camp**: today's encounter, rewritten as data. Outdoors, unaware, 3 raiders.
2. **Roadrunner den**: inside `newriver/2_2/0` (the Roadrunner, a restaurant), with interior history `den`. A sentry sits at a front window, and the camp is in the dining room with the boss near the stash. This is the one fight the interiors brief asks combat to make happen inside the Roadrunner.
3. **Ranch-house holdout**: inside `newriver/2_2/31`, history `holdout`, 2–4 survivors, attitude `wary`. Windows are boarded and the front door is barricaded. You can talk, leave, or force your way in.

There's also an optional road patrol between the store and the bridge. If the Roadrunner gets loud, it reinforces.

**Done when.** All three load from JSON, and the bridge camp plays exactly as it does today.

---

## 4. Classes and weapons for survivors

**Goal.** The original game's four roles, adapted to survivors with real-world weapons. A role describes what a person carries and is practised at, not a rank. It comes from skills that `people.md` will own.

| Role | From | Weapon (profile) | Signature action | Indoors |
|---|---|---|---|---|
| **Ranger** | Ranger | Pump shotgun (short), machete (melee) | *Run and gun*: shoot after a dash | Best room-clearer. +10 aim under 6 m. |
| **Sharpshooter** | Sharpshooter | Bolt-action hunting rifle (long), revolver | *Squadsight*: shoot anything a teammate sees, beyond 24 m | Weak: −10 aim under 8 m. Covers doors from outside. |
| **Breacher** (was Grenadier) | Grenadier | Shotgun or carbine (mid), pipe bombs, door charge | *Breach charge*: blows a barricaded door or boarded window | Opens what others can't. |
| **Medic / Tinker** (was Specialist) | Specialist | Pistol or carbine (mid), first-aid kit, lock picks | *Stabilise* a downed ally; *pick* a locked door quietly | Gets the squad in without noise. |

- **Weapons** take their numbers from `index.html` (`dmg`, `crit`, `critDmg`, `ammo`), scaled to the foundation's damage of 3–5. Reloading takes 1 action, and ammunition comes from the `gear` loot category.
  - Range profiles: `short` gets +10 under 6 m and −2 a metre beyond 12 m. `mid` matches today's numbers. `long` gets −10 under 8 m and no fall-off up to 40 m.
- **Throwables** (replacing grenades):
  - Pipe bomb: radius 3 m, 3 damage, destroys cover.
  - Molotov: radius 2 m, sets the cells on fire for 2 rounds.
  - Flashbang: stuns for 1 turn and makes noise.

  Explosives break doors and windows but not walls.
- **Crossbow** (an optional fifth weapon): no noise radius. A miss or a silent kill doesn't break concealment. This matters a lot indoors.

**Done when.** The squad roster carries role and weapon, the action bar shows role actions and ammo, and the odds use weapon profiles. The rule tests in task 1 cover each profile.

**Needs from others.** `models.md` and `animation.md` supply weapon models and poses for reload, throw, kick, climb and stabilise. Boxes stand in until then.

---

## 5. Wounds and deaths written back to the squad

**Goal.** A fight changes the people in it. `people.md` owns health. Combat reports what happened.

- **Downed, not dead**: a squad member at 0 HP is *down* and bleeds out after 3 of their own turns. An adjacent Medic can *stabilise* them (1 action, uses a first-aid kit), and they stay down for the rest of the fight. A crit hit while already down kills. Raiders die at 0 HP, as today.
- **Wounds**: each hit records a severity from its damage relative to max HP: `light` under 34%, `serious` under 67%, otherwise `critical`. Healing time and lasting effects belong to `people.md`.
- **Panic**: the panicked ink exists already. When an ally dies within sight, roll will (a `people.md` value, 50 until it exists). A failure costs the unit its next turn: it moves away from foes, or hunkers.
- **Result record**, sent through `CB.onEnd(result)`:

```json
{
  "encounter": "newriver/roadrunner-den", "outcome": "cleared",
  "rounds": 6, "gameMinutes": 210,
  "people": [ { "id": "rosa", "hp": 2, "max": 6, "status": "wounded",
               "wounds": [ { "sev": "serious", "round": 3 } ] },
              { "id": "dev", "status": "dead", "round": 4 } ],
  "enemies": { "killed": 3, "fled": 1 },
  "used": { "ammo": 11, "firstAid": 1, "pipeBomb": 1 },
  "changes": [ "door:front=broken", "window:3=broken", "item:42=destroyed" ]
}
```

- The region map's squad keeps a list of people, not just a head count. Today `squadInfo.people` is a number, so this needs a small change in `strategy-map.md`.
- `changes` goes into the interior's change record (see 7g).

**Done when.** Wounded people stay wounded after zooming out and back in. The dead are gone from the squad, and the result record is logged.

---

## 6. World clock in fights

**Goal.** A fight costs world time: 5 game minutes per character turn, for the squad and enemies alike (foundation).

- Each time a unit's turn ends, call `rt.clock.advance(5)`. Downed units and units that skipped a turn count too. The strategy map exposes `__region.advance(minutes)` and `__region.now()`. Today time doesn't pass on the tactical ground at all (strategy-map known gap). This change gives it a clock while fighting, and strategy-map task 5 decides the rate while exploring.
- The HUD shows the time of day next to the round, e.g. `14:35 · Round 3`. When it crosses 18:00, it warns "Dusk in 20 min".
- **Daylight changes sight** (to agree with the foundation, so propose it in the PR):

  | Time | Raider sight | Squad spotting |
  |---|---|---|
  | Day | 16 m | 30 m |
  | Dusk/dawn | 12 m | 20 m |
  | Night | 8 m | 12 m |

  A lit fire or lantern lets anyone see the units near it from twice as far. A raider den with a fire barrel is easy to see into and its occupants are night-blind toward the dark.
- Water and food drain on the world clock, as the foundation says. Combat just advances time, and `people.md`/`strategy-map.md` settle the drain.

**Done when.** An 8-round fight with 4 squad members and 3 raiders advances the clock by about 4.7 hours, the HUD shows it, and the map reads the new time after zooming out.

---

## 7. Fighting inside buildings (interior encounters)

**Goal.** A squad can walk up to any generated building and fight in, out of and through it.
- Rooms, doors, windows and furniture all count.
- The fight can start with a breach.
- Raiders hold rooms, cover doorways and fall back.
- The ground outside joins seamlessly: windows look out, doors lead out, and noise carries.

The interior generator already provides the plan, openings, furniture cover, history and people. This task turns that into a combat world and builds the rules that only matter indoors.

### 7a. One movement graph, several grids

The outside uses 2 m cells with blocked *cells*. Inside, it's 1 m cells with blocked *edges*, rotated to each building's axis. Keep both. Combat works on **nodes**:

- `node = layer << 20 | index`. Layer 0 is the ground grid, layers 1–15 are bridge decks, and layers 16 and up are one per loaded interior.
- The world adapter (task 1) answers the same questions for every layer: position, neighbours with costs, cover toward a point, sight between two nodes.
- **Reach stays in effective metres** (12 per action), so mixing 1 m and 2 m steps doesn't change how far anyone goes.
- Indoor step cost: 1 m divided by the floor speed (1.0, or 0.6 over debris).
  - Passing an open or broken door is free; opening a closed one costs +1 m and makes door noise.
  - Climbing through a window costs +4 m, and +1 m more for broken glass, which also makes glass noise.
  - Boarded and barricaded openings are closed to movement (see 7c).
- **Joining inside and out**: every exterior door and window edge links its inside cell to the nearest passable 2 m outdoor cell (the same link `interiors.md` task 3 needs for walking). The footprint cells on the ground grid stay `building`, so outdoor paths go around unless they pass through a door link.

**Needs from `interiors.md`.** A combat view of a generated building (draft below, for interiors to own and shape):

```js
Interiors.combatView(gen) -> {
  id, floorY, cellCount,
  toWorld(c) -> [x, z],  cellAt(x, z) -> c | -1,
  speed(c) -> 0..1,                      // 0 under furniture that can't be crossed
  edge(c, dir) -> { kind: 'open'|'wall'|'door'|'window', state, id },
  item(c) -> { id, cover: 0|1|2, h } | null,
  rooms, roomOf(c),
  exits: [ { id, kind, role, edge, cell, outside: [x, z] } ],
  people: [ { c, side, boss } ],
  set(id, state)                          // doors, windows, items → change record
}
```

### 7b. Sight and cover through walls

- **Sight**: walk the 1 m cells between the two eye points (1.5 m, or 1.0 m when hunkered) with grid traversal (DDA), checking each edge crossed:

  | Edge | Sight | Shots |
  |---|---|---|
  | Wall | blocked | blocked |
  | Closed or barricaded door | blocked | blocked |
  | Open or broken door | passes | passes |
  | Intact window | passes | pass and break it (glass noise) |
  | Broken window | passes | passes |
  | Boarded window | blocked | blocked |

  Furniture taller than the eye (shelving, coolers, wardrobes) blocks sight through its cells. Lower furniture doesn't. When a line leaves the footprint through an opening, it continues on the ground grid using today's `los`.
- **Cover** toward a shooter looks at the one or two edges of the unit's cell that face the shooter, in the building's frame:
  - a wall or closed door gives **full**;
  - a window gives **half** (the sill), and flanking through the window is possible;
  - otherwise, the item in the neighbouring cell gives its cover (`half` or `full` from the kit).
  
  If nothing is there, the unit is flanked, as today. Units outside get full cover from the building's exterior walls, which fixes the known gap about parapets for buildings.
- **Destruction**: explosives turn furniture within the radius into debris (cover none, slow floor), break doors and windows, and stop at walls. A shot that misses through an intact window breaks it.

### 7c. Doors, windows and the breach

These are new actions, shown only when relevant:

- **Open/close door**: free as part of a move; 1 action to close one without moving through it (it blocks sight for the enemy's turn).
- **Kick door**: 1 action, 20 m noise. It works on closed doors, and on locked ones too if `interiors.md` adds a `locked` state.
- **Pick lock**: Medic/Tinker only, 1 action, silent.
- **Pry boards / barricade**: 2 actions, 14 m noise. A Breacher's charge does it in 1 action with explosion noise and 2 damage to anyone within 2 m inside.
- **Climb through window**: part of a move (see costs in 7a).

**Breach** is the indoor version of first strike. It's allowed while the encounter is `unaware` or `suspicious` and the squad hasn't been seen.

- Squad members *stack* at entry points: any exterior door or window within one move. Each picks their entry.
- Confirming the breach opens every chosen entry at once (kicked, charged, picked or climbed). Each breacher gets one free shot at anything visible from their entry, with +10 aim. Targets are coverless only if they were unaware.
- Penalties: −10 aim through a window climb, −15 for a suspicious pod.
- Then the normal squad turn begins with full actions, as first strike does today.
- If the encounter is already alert, there's no breach: going through a door is a normal move into overwatch.

### 7d. Placing the occupants

- Treat `decay().people` as spawn hints, and give roles from the plan:
  - **sentry**: at a window cell facing the road (`sense.front`), stance `watch`, cone out of the window;
  - **camp**: in the largest room with bedrolls, stance `idle`;
  - **boss**: the cell nearest the stash crates;
  - **sleeper** (night only): on a bedroll, gets a −1 action on its first turn.
- An encounter file can override these with `pods[].room` or `pods[].edge`. The same building id and seed always give the same layout, as the interiors decision requires.
- `interiors.md` could later store the role itself. Until then, combat assigns roles and the generator doesn't have to change.

### 7e. Raider tactics indoors

The greedy per-unit AI stays for open ground. Indoors, add a short list of room behaviours, chosen per pod each turn:

- **Hold**: stay in a room with cover, and put overwatch on the doors into it. Use *doorway overwatch*: a reaction shot when an enemy crosses the watched door edge, at no −15 penalty because the door is pre-aimed.
- **Fall back**: when a pod has lost half its members, or the squad holds the room's main door, move to an inner room through a back door and close it.
- **Flee**: when the boss is dead or the pod is below `retreat.below`, leave by the exit furthest from the squad. Units that get out of sight count as `fled`, and the strategy map keeps them as an aggregate (they can come back as a roaming threat).
- **Investigate** (suspicious): one unit walks to the noise source while the rest hold.
- The boss never leaves the stash room unless fleeing.

These are `chooseAction` branches in `rules.js`, tested headless on a fixed seed for the Roadrunner.

### 7f. Holdouts (wary survivors)

- Getting into a holdout's sight (through a window, or by knocking on a door) raises a **hail** prompt instead of combat. The prompt offers *Talk*, *Leave* or *Force entry*.
  - *Talk* hands over to `settlement.md`/`people.md` for trade or recruiting, and combat only reports it.
  - *Leave* marks the encounter `avoided`.
  - *Force entry* turns them hostile, and they get the initiative.
- Shooting near them, or breaching their building, turns them hostile with no prompt.
- Survivors use the indoor AI above, but they **flee sooner** (below 70%) and **surrender** at 1 left. Surrender is a result for `people.md` to handle (captives, recruits).

### 7g. Loot and changes after the fight

- After `cleared`, the interior's containers become searchable. Searching costs world time per container (`strategy-map.md` sets how much). The den's stash crates hold `gear | food | fuel | medicine`, as `stockLoot` already says.
- Raider bodies drop their weapon and remaining ammo as a container on their cell.
- Everything the fight changed is written to the interior's change record (`{doors:{}, taken:[]}` already exists in `freshRecord`): doors broken, windows broken, items destroyed, bodies. Coming back shows the aftermath.

### 7h. Order of work for 7

1. **Headless first**: in a test page, load the Roadrunner from `tools/interiors/sites.json` with history `den`. Build the combat view and run sight, cover and reach checks. Assert against a hand-checked map: no sight through walls, sight through the open front door, full cover behind the counter.
2. **Interiors mockup with combat**: drop `rules.js` and `view.js` into `mockups/interiors.html` behind a "Fight here" toggle. Squad at the front door, den occupants in place, breach, turns. This doesn't need streaming yet and can be published as an Artifact.
3. **In the streamed world**: once `interiors.md` task 3 joins its grid to the movement grid, generate interiors within 50 m during exploration. Lock them while a fight is on, so a fight never drops a building. Hand the Roadrunner encounter (task 3) to the zoom page.
4. **Holdout house**: hail, talk/leave/force, surrender.
5. **Tuning pass in a real browser**: breach odds, doorway overwatch and fall-back thresholds. Write the numbers into `combat.md` Decisions and flag them for the foundation.

**Done when.** In the zoom page you can:
- walk to the Roadrunner, see the sentry through the window, stack at the front door and back door, and breach;
- fight room to room, with the cutaway showing everyone;
- clear the den, or have raiders flee out the back;
- search the stash, zoom out and back in, and find the doors still broken and the stash empty.

### Proposals for other topics (to raise in the PR)

- **`interiors.md`**:
  - a `combatView(gen)` view, or something like it;
  - a `locked` door state;
  - optionally a `role` on generated people;
  - wall groups split by facing for the cutaway.

  Also, its brief's "Where it stands" is out of date.
- **`tactical-maps.md`**: `userData.cutaway` tags on deck and roof meshes, and the door/window links between interior and outdoor cells.
- **`strategy-map.md`**: the encounter format (task 3), `__region.advance/now`, squads carrying people rather than a count, and `fled` raiders as a regional aggregate.
- **`people.md`**: the wound severities, will for panic, and surrender and captives as results.
- **Foundation**: the daylight sight table and the noise radii.
