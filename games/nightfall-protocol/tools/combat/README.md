# Combat tools

Fighting inside procedurally generated buildings (task 7 in `briefs/combat-tasks.md`), with free placement: units stand at any point, not on a grid. Nothing here edits the interiors code. The interiors topic owns `tools/interiors/`, so this folder only reads it.

- `interiors-slice.js` cuts the generator, its renderer and its physics (grenades scattering props, overturning) out of `tools/interiors/interiors.src.html` by marker comments, and inlines `kit.js` and `sites.json`. If the interiors page moves a marker, the build and the tests stop with a message.
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
- `rules.js` holds the foundation's combat values as plain, seeded functions over points.
  - **Roles** (`ROLES`), the original game's four classes adapted to survivors:

    | Role | Weapon | Ability |
    |---|---|---|
    | Ranger | pump shotgun | Run and gun: one extra action, every 3 rounds |
    | Sharpshooter | hunting rifle | Steady aim: +15 when the shot is the first action of the turn |
    | Breacher | carbine | 2 pipe bombs, and a charge that blows barricades and boards at a breach |
    | Medic | pistol | 2 first-aid kits: heal 3, stabilise someone bleeding out, or get a stabilised ally up |

  - **Weapons** (`WEAPONS`) have range profiles: short gets +15 under 6 m and −2/m past 12 m; mid keeps the foundation's numbers; long gets −10 under 8 m and no fall-off to 40 m. Each weapon also sets damage, crit and ammo, and reloading takes an action.
  - **Explosions**: pipe bombs reach 3 m and do 3 damage (4 within 1 m), ignoring cover. They blow apart furniture, blow doors in and break glass. Walls and closed doors shelter.
  - **Wounds**: squad members at 0 HP go down and bleed out after 3 of their own turns unless the Medic reaches them. Raiders die at 0 HP.
  - **Morale**: once the boss is down or half the pod is gone, each raider may break and run for the exit furthest from the squad, escaping once outside and out of sight.
  - **Doorway overwatch**: a reaction shot at someone in a doorway or window has no −15 penalty, because the spot is pre-aimed.
  - `odds` returns the reasons with the numbers, so the page can show where every percentage comes from.

  The functions:
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
- `testmap.js` is the **test range**, a hand-laid 32 × 22 m building, first in the page's building list. It is not procedural; the interiors generator's own helpers (footprint frame, room records, colours) are called, never changed. It holds every case the rules handle, labelled in the page (the Labels button):
  - four rooms off a long lane, each showing the lane a different wall build-up: drywall and stucco let rounds through, block stops them, reinforced concrete takes two charges; a raider stands behind each;
  - a 32 m lane, end to end, for range profiles and corridor overwatch, with a raider at the far end and one half-cover crate;
  - windows of every sill and state: 0.6, 0.9, 1.0 and 1.2 m (climbable), 1.8 m (too high), broken and boarded;
  - front double door, side door into the lane, back door; inside, open and closed doors, a 3 m archway, and counters (half cover you can see and climb across);
  - a cover gallery with full, half and flippable pieces in rows, and the stash safe;
  - a drywall wall between the stockroom and the gallery to breach, and a low and a high yard wall outside;
  - every enemy type: boss, brute, two enforcers, five raiders (one a sentry at a window);
  - three ladders to the roof (west, south front, east), for peeking in through a blown hole.

  `test-space.js` checks that the range still has all of these.
- `roof.js` makes the roof a second level. Units carry `lv` (0 ground, 1 roof); the rules ask the space's `levelLine` and `levelCover` whenever someone is on the roof, and roof.js answers:
  - **roof and outside ground**: you see over the edge only from within 2 m of it; the parapet is half cover;
  - **roof and inside**: only through a hole, from its rim (within 1.1 m), down to anyone within 6.5 m of the hole; full cover counts as half when shot from above;
  - **roof and roof**: the roof's own space (the footprint, its outer walls as a parapet, holes blocked), which also routes movement up there;
  - shooting down gets +10 (**Height**); melee and blasts stay on their own level.

  **Ladders** on outside walls (the test range has three) join the levels with the motion module's ladder and descend clips. On the roof a **Breacher's charge** opens a 2 × 2 m hole into one room (never over a wall): debris hits whoever is under it. Then **peek** from the rim to see and shoot in, throw a pipe bomb down, or **drop through** with the drop clip. Exploring, a roof charge starts the fight with the squad's free shots. The roof deck shows while anyone of the squad is up there.
- **Screen** (kept quiet on purpose): one header row (building, history, Restart, and a *View* menu with the toggles and the keys); soldiers are selected by clicking them in the scene (Tab: next), not from a list; their health shows as small pips over them and the selected soldier's card sits in the HUD; the bottom bar holds only what applies (Go in a fight; Breach, Open fire, Take the stash while exploring); raider badges show just the hit chance (gold when flanked, ×2 when two soldiers are on them); the reach is the outline alone; banners are short; the log shows its last lines and opens on hover; the test range's labels are off by default.
- **Strict rounds** (mockup: `mockups/combat-interior-rounds.html`, flag `window.COMBAT_STRICT`):
  - **No real-time exploring**: the mission is in rounds from the start, the raiders unaware.
  - **Moving is per soldier and happens at once**: click the ground and the soldier runs there now, within the round's 12 m allowance (more legs are fine while it lasts); a dash beyond it, up to 12 m more, spends that soldier's action. Overwatch fire can catch them on the way; an unaware raider who sees them raises the alarm (and the clock on reinforcements). Climbing a ladder or dropping through a roof hole costs 4 m.
  - **What the moved soldier then sees is the intel**: raiders they see appear, and rooms open.
  - **Actions are queued and carried out together on Go** (shoot, breach an entry, throw, charge, overwatch, hunker, aid …); then the raiders act together; then a new round.
  - **Three cameras** (header, or V): *Shoulder* (over the selected soldier; drag turns, wheel distance), *Isometric* (fixed angle, Q/E turn in quarters, WASD or drag pans, wheel zooms), *Top* (straight down, squared to the building).
  - **The building stays closed until someone has a vantage**: before any soldier has seen in, it shows only its outside (walls whole, roof on). From outside, a soldier sees in only through an opening within 2.5 m of where they stand; inside, they see normally; on the roof, through a hole. A room seen once opens for good (the cutaway, or the plan from the top); rooms no one has seen stay dark blocks, and so does the stash's label. Over the shoulder, walls stay whole while the soldier is outside.
- **Third person, free** (mockup: `mockups/combat-interior-free.html` starts in it; elsewhere V or *View ▸ Third person*): the camera goes over the selected soldier's shoulder and you control them directly.
  - **Exploring**: WASD walks them crouched and quiet (Shift runs, and is heard); doors open as you pass, low windows and counters are vaulted; the others follow in a file behind and to the left (H: hold); F uses what is at hand (ladder, stacking at an entry, the stash, a door, a hole in the roof, a downed squadmate).
  - **Fighting**: once anyone fires, the fight runs in real time instead of rounds. The mouse aims (click the view to lock the pointer; without a lock the crosshair follows the cursor), a click fires a round along the crosshair with sway from skill and movement, real cover stops it and the head is a crit; the right button steadies the aim; R reloads; C crouches (hunkered); G throws a pipe bomb at the crosshair, X sets a charge on the wall ahead or the roof below. Raiders and the other soldiers act on their own timers with the same `decide` as in rounds; bleeding, morale and reinforcements run on the clock. Tab changes soldier; if yours goes down, control passes on. V (or *Back to rounds*) returns to planned rounds.
- **The squad up close** (in `demo-script.js`), after XCOM's closeness to its soldiers:
  - **faces**: each soldier's portrait is their own generated face, rendered once into the bar and into a card for the selected soldier (name, nickname, rank, class, missions, kills, HP pips, bleeding countdown);
  - **voices**: short lines at the moments that matter: acknowledging the player, saying what they are about to do on Go, kills, misses, *I'm hit*, a squadmate going down, the medic reassuring, a wasted shot; raiders shout when they spot you, get hit or break;
  - **the shot camera** (*Action cam*, on by default): when someone fires, the camera goes over their shoulder with the target in frame and letterboxes the screen, slowing on a kill; one shot at a time, the rest play on. Hovering *Shoot* or *Free shot* in a raider's menu previews that view from where the soldier will stand.
- **Debug copy**: `mockups/combat-interior-debug.html` (build.py writes both), for testing without the hiding. Every raider is shown with their sight cones, lines of fire run from the selected soldier to each raider (green: a line, red: none), and a panel switches raiders blind (never spot the squad), raiders passive, and the squad unhurtable; it starts the fight, fast-forwards ×4, refills ammo and kit and heals. Alt+click puts the selected soldier anywhere; K kills the raider under the cursor; the cursor readout gives the point, who would see you there, your cover against each raider and how many you have a line to. The panel is `debug.js`; the fight code reads its switches (`DBG`) only when `window.COMBAT_DEBUG` is set.
- `demo-script.js` and `demo.src.html` are the playable page.
  - **Pacing**: exploring is real time. A fight runs in rounds: you give every soldier orders, then press Go and the whole squad carries them out at once; then the raiders all act at once. Shots resolve as each soldier gets there, so two soldiers sent onto the same raider can find the second shot has nothing left to hit (the log says so and the summary counts wasted shots). Each raider badge shows how many shots are planned on them and their HP, and turns pink when more than one is.
  - **Orders**: left click moves the selected soldier, inside the blue outline (move, then act) or the gold one (dash, no action). Right click a raider for that soldier's attacks with odds from where they will stand (free shot, shoot, shooting through a thin wall, revolver, slash, pipe bomb). Right click a thing for what can be done to it (stash, overturn furniture, close a door, set a breaching charge on a wall, get out), the soldier for their own actions (overwatch, hunker, reload, run and gun, first aid), and the ground to move then overwatch or hunker. There is no separate action menu.
  - **Picking and camera**: raiders and soldiers are picked on screen along their whole figure, so a click on a raider's body opens their options (left or right click); the cursor changes over them. WASD moves the camera over the ground, Q and E turn it, the wheel zooms, a right drag pans. The banner and panels never catch clicks.
  - **Cutaway** (the interiors' section cut): walls between the camera and the focus drop to a 0.9 m stub, filled with their build-up's tone, with doors and windows drawn as plan symbols. The focus is the floor under the pointer while it moves over the building, otherwise whoever the camera follows. `stepCut()` is sliced from the interiors page by name. Off in first-person overwatch.
  - **Moving props**: right click a table, shelf or tipped prop for *Shove it clear* (the nearest spot off every doorway) or *Drag it to…* (up to 8 m), using the interiors' `shove` and `dropAt`; the move goes in the change record and the space follows it.
  - **Windows**: soldiers climb through any window with a sill up to 1.3 m (the motion module's vault; the glass breaks on the way). Higher windows (bathrooms, high storefront glazing) can be seen and shot through but not climbed.
  - **What you see**: only the raiders your squad can see are drawn. A raider who fires or is hit shows briefly; one who slips out of sight leaves a "last seen ?" mark. The camera is low with a narrow lens (26°), so you read the room from the squad's level.
  - **Hover**: a ring where the unit would stand, the route there, and a marker toward each raider in sight: tall gold for full cover, short gold for half, flat red for flanked.
  - **Breach**: stack on the gold (door) and blue (window) rings (right click one), then breach; free shots fire the moment you press Go.
  - **Walls**: a Breacher's charge cracks, holes or breaches a wall by its build-up (the interiors decide); shots go through stud walls, frame walls and closed doors at a penalty, not block or concrete.
  - **Motion**: the shared motion module poses the figures: crouch-walking while concealed, aiming, shooting, reloading, hunkering, falling, and vaulting through windows.
  - **End**: the summary counts kills, escapes, the squad's wounds and dead, hits, wasted shots and the daylight spent.

  The interiors renderer draws the building, including its cutaway walls.

## What came from the earlier iterations

The original game (`index.html`) and the outdoor demo (`tools/zoom/combat.js`) were reviewed. These features are carried over:

| Feature | From | Here |
|---|---|---|
| Real-time exploring that folds into turns; time slows at contact, then engage or hold back | outdoor demo | explore phase, `contactCheck` |
| Patrols while unaware | original game | one raider walks a loop between rooms |
| Enemy types: Lancer (fast melee), Warden (armour), Officer (defence) | original game | Brute (machete, +3 m reach per action, defence 10), Enforcer (armour 1, 8 HP), boss (defence 5) |
| Armour soaks damage; explosives shred it | original game | `roll`, `blastHits` |
| Ranger's blade; Sharpshooter's pistol | original game | Slash (run in and strike, +10, no cover); Revolver (no reload) |
| Objective, way out, reinforcements | original game (hack relay, evac, reinforcements 2 turns later) | take the generator's stash, reach the green ring; two raiders from the road 3 raider turns after the shooting starts |
| Hit badges, FLANK tags, odds with damage range | original game | badges over raiders (hit %, FLANKED, FLANK from the hovered spot, armour pips) |
| First-person overwatch | original game | "Aim overwatch": the watcher's eye, the mover at 1/7 speed, sway by aim, a head hit is a crit, cover stops the bullet, 5.5 s (6.5 s scoped) before the roll decides |
| Ranks, XP, nicknames, memorial | original game | XP for kills and a win; +1 HP and +3 aim a rank; the dead go to the memorial and a rookie takes their place (kept in this browser) |
| Camera: focus on blasts, looking around pauses the follow | original game | `camHold` |

The demo also uses work from the other sessions:
- the interiors physics: pipe bombs scatter props, and soldiers can overturn tables and shelves for cover;
- the motion module: weapons in hand, recoil, hit reactions, reloads, a ragdoll when someone goes down, and getting back up after first aid.

Not ported:
- hacking: there is no relay in these buildings;
- the 12-turn timer: daylight and reinforcements carry the pressure instead;
- height bonus: interiors are level, but outdoors needs it when this joins the streamed ground.

Build with `python3 tools/combat/build.py [artifact-fragment.html]`. It writes `mockups/combat-interior.html`. Published as https://claude.ai/artifact/Xm7C2fNtxDRpa57hQ2CYcW

The page exposes `window.__combat`, with `S.timeScale` for tests on slow software rendering.
