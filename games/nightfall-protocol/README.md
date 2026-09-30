# Nightfall Protocol

A turn-based squad tactics game inspired by XCOM 2. It is one self-contained HTML file with no build step. Open `index.html` in a browser to play. The 3D view uses [three.js](https://threejs.org/) r128, loaded from cdnjs, so the first load needs an internet connection and a browser with WebGL.

## What's in it

- **3D battlefield**: an angled camera like XCOM's that you can rotate, zoom and drag, and that follows the action. Walls, cars, trees, crates and the relay terminal cast real-time shadows. Tactical overlays (move ranges, paths, detection zones, fog of war) are painted onto the floor.
- **Character models and animation**: every class and enemy type is a low-poly model built in code, with its own armor, silhouette and weapon. The Ranger's Arc Blade glows on its back, the Specialist's drone orbits, the Officer wears a cape and the Warden is a hulking heavy. Soldiers walk, raise their weapons to aim, recoil when firing, kneel on overwatch, crouch to hunker down, flinch when hit and fall when killed. Soldiers also swing blades, throw grenades, hack, reload and lift off on evac.
- **Effects**: tracer rounds, muzzle flashes, impact sparks, explosions with debris and smoke, reinforcement drop beams and hacking links.

- **4-soldier squad**: Ranger (shotgun + Arc Blade slash), Sharpshooter (sniper with squadsight + pistol), Grenadier (cannon + grenade launcher), Specialist (rifle + aid drone, remote hacking).
- **Two actions per turn**: move within the blue range (1 action) or dash into the amber range (2). Firing ends the soldier's turn.
- **Cover and flanking**: half cover gives −20 to enemy aim and full cover −40. If no cover faces the shooter, the unit is flanked and the shot gets +50% crit chance. Shield icons show cover at the hovered tile, and FLANK tags show which enemies you would flank from there.
- **Overwatch, hunker down, reload, grenades**: explosives destroy cover and shred armor.
- **Concealment**: the squad starts hidden. Red tiles mark where patrols would detect you. Ambush a pod with overwatch.
- **Mission timer**: hack the relay within 12 turns. Reinforcements drop two turns after the hack. Then kill every hostile or evacuate.
- **Enemy AI**: patrolling pods scramble to cover when they activate. They pick firing positions based on cover and flanking, and they overwatch when they have no shot. Stun Lancers rush your soldiers.
- **Campaign**: survivors earn XP, ranks and nicknames. The dead go on the memorial and rookies replace them. Difficulty rises with each mission. Progress is saved in `localStorage`.

## Controls

Click a soldier to select, then click a tile to move. `1`–`8` pick actions, `Tab` cycles soldiers or targets, `Enter` confirms, `Esc` cancels, and `Backspace` ends the turn. `Q`/`E` rotate the camera, the mouse wheel zooms, and dragging pans (the camera re-centres on the next action). On touch devices, tap a tile once to preview the move and again to confirm it. The on-screen buttons rotate and zoom.
