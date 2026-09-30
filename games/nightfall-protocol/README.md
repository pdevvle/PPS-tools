# Nightfall Protocol

A turn-based squad tactics game inspired by XCOM 2. It is one self-contained HTML file with no build step. Open `index.html` in a browser to play. The 3D view uses [three.js](https://threejs.org/) r128, loaded from cdnjs, so the first load needs an internet connection and a browser with WebGL.

## What's in it

- **3D battlefield in a "crash-test dummy" low-poly style** (think Ravenfield): clean, brightly lit low-poly models in bold team colours under daylight. The angled tactical camera rotates, zooms and pans, and it follows the action. Each map picks a consistent look per building and per barrier line from the prop catalog below, set in a small town with a road loop, houses, power poles, streetlights and trees. Tactical overlays (move ranges, paths, detection zones, fog of war) are painted onto the floor.
- **Mannequin soldiers**: every soldier is a glossy plastic mannequin (blue for the Resistance, red for the Directorate) with the following build:
  - a lathe-turned torso and pelvis and a faceless egg head
  - dark ball joints at the neck, shoulders, elbows, wrists, hips, knees and ankles
  - mitten hands with thumbs and boots
  - yellow/black crash-test markers on the head, arms and thighs

  Each class wears readable kit over the plastic:
  - Ranger: shemagh, headband tails, plate carrier and an Arc Blade on the back
  - Sharpshooter: boonie hat, rangefinder, a ghillie cape and a scoped rifle with bipod
  - Grenadier: helmet with a tinted visor, shoulder and thigh plates, a grenade bandolier and a drum-fed launcher
  - Specialist: headset helmet with a HUD eyepiece, a wrist computer, a medic cross and a quad-rotor drone

  The Directorate wear charcoal plate with glowing red trim and visor slits. Troopers carry breather tanks. Officers have peaked caps, gold epaulettes and capes. Lancers wear finned helmets. The Warden is a heavy-plated brute with a reactor pack.
- **Prop catalog** (about 45 props, all built from code with no textures). The categories correspond to the game's cover rules:
  - **Full cover**: concrete, brick and corrugated-metal walls, plus windows with a low sill
  - **Half cover**: wooden crates, ammo crates, oil drums, tire stacks, a generator, a dumpster, a sack pallet, an AC unit and tarped crates
  - **Barriers**: jersey barriers, sandbag walls, concrete blocks, striped road barriers and planters
  - **Vehicles**: sedans, pickups (sometimes loaded with crates), taxis and burnt-out wrecks
  - **Trees**: pines, oaks and dead trees
  - **Street dressing** (never blocks shots): cones, hydrants, trash cans, benches, boxes, pallets, trash bags, tires, rocks, grass, bushes, streetlights, road signs, power poles, mailboxes and houses

  **Catalog** (in the header or on the briefing) opens a turntable viewer. Drag to spin a model, use ← → to browse, and use **Variant** to roll another random build of a prop.
- **Animation**: soldiers walk, raise their weapons to aim, recoil when firing, kneel on overwatch, crouch to hunker down, flinch when hit and fall when killed. They also swing blades and lances, throw grenades, hack, reload and lift off on evac. Effects include tracers, muzzle flashes, impact sparks, explosions with debris and smoke, drop beams and hack links.
- **First-person overwatch**: when an enemy moves into an overwatching soldier's sight, time slows and the view switches to that soldier's eyes, stepping out from cover. Aim with the mouse (or drag on touch) and fire with a click, Space or the Fire button. The shot is a real raycast:
  - Walls, crates and cars in the way stop the bullet.
  - A headshot is a critical hit.
  - Low-Aim soldiers sway more.
  - Sharpshooters look through a zoomed scope.

  If you don't fire before the timer runs out (or you press Esc), the shot is rolled automatically at the usual −15 aim. **Manual aim: on/off** at the top switches between first-person and fully automatic overwatch.
- **4-soldier squad**: Ranger (shotgun + Arc Blade slash), Sharpshooter (sniper with squadsight + pistol), Grenadier (cannon + grenade launcher), Specialist (rifle + aid drone, remote hacking).
- **Two actions per turn**: move within the blue range (1 action) or dash into the amber range (2). Firing ends the soldier's turn.
- **Cover and flanking**: half cover gives −20 to enemy aim and full cover −40. If no cover faces the shooter, the unit is flanked and the shot gets +50% crit chance. Shield icons show cover at the hovered tile, and FLANK tags show which enemies you would flank from there.
- **Overwatch, hunker down, reload, grenades**: explosives destroy cover and shred armor.
- **Concealment**: the squad starts hidden. Red tiles mark where patrols would detect you. Ambush a pod with overwatch.
- **Mission timer**: hack the relay within 12 turns. Reinforcements drop two turns after the hack. Then kill every hostile or evacuate.
- **Enemy AI**: patrolling pods scramble to cover when they activate. They pick firing positions based on cover and flanking, and they overwatch when they have no shot. Stun Lancers rush your soldiers.
- **Campaign**: survivors earn XP, ranks and nicknames. The dead go on the memorial and rookies replace them. Difficulty rises with each mission. Progress is saved in `localStorage`.

## Controls

Click a soldier to select, then click a tile to move. `1`–`8` pick actions, `Tab` cycles soldiers or targets, `Enter` confirms, `Esc` cancels, and `Backspace` ends the turn. `Q`/`E` rotate the camera, the mouse wheel zooms, and dragging pans (the camera re-centres on the next action). On touch devices, tap a tile once to preview the move and again to confirm it. The on-screen buttons rotate and zoom. In first-person overwatch: move the mouse to aim, click or `Space` to fire, arrow keys to fine-tune, `Esc` to auto-fire.

## Mockups

- `mockups/survivor-style.html` is a style test that rebuilds the squad and two Directorate enemies the way Project Zomboid builds its characters: realistic proportions, with clothing, faces and dirt or blood painted onto textures generated in code. It uses the game's joint layout and model kit. You can switch between isometric, close-up and face views, change the wear level, and flip back to the current mannequins to compare.
- `mockups/base-figure.html` is a stripped-down figure study: two unclothed base bodies with lanky, realistic proportions (about 6 heads tall), a relaxed stance, and anatomy painted into low-resolution skin textures. It has front, ¾, side, back, in-game and face views, head-unit guides, skin tones, a pixel/smooth texture switch and a walk cycle.
