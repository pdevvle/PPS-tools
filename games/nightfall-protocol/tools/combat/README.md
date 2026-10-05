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
- `demo-script.js` and `demo.src.html` are the playable page.
  - **Pacing**: exploring is real time. A fight runs in rounds: you give every soldier orders, then press Go and the whole squad carries them out at once; then the raiders all act at once. Shots resolve as each soldier gets there, so two soldiers sent onto the same raider can find the second shot has nothing left to hit (the log says so and the summary counts wasted shots). Each raider badge shows how many shots are planned on them and their HP, and turns pink when more than one is.
  - **Orders**: left click moves the selected soldier, inside the blue outline (move, then act) or the gold one (dash, no action). Right click a raider for that soldier's attacks with odds from where they will stand (free shot, shoot, shooting through a thin wall, revolver, slash, pipe bomb). Right click a thing for what can be done to it (stash, overturn furniture, close a door, set a breaching charge on a wall, get out), the soldier for their own actions (overwatch, hunker, reload, run and gun, first aid), and the ground to move then overwatch or hunker. There is no separate action menu.
  - **Picking and camera**: raiders and soldiers are picked on screen along their whole figure, so a click on a raider's body opens their options (left or right click); the cursor changes over them. WASD moves the camera over the ground, Q and E turn it, the wheel zooms, a right drag pans. The banner and panels never catch clicks.
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
