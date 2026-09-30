# Nightfall Protocol

A turn-based squad tactics game inspired by XCOM 2. It is one self-contained HTML file with no build step. Open `index.html` in a browser to play. The 3D view uses [three.js](https://threejs.org/) r128, loaded from cdnjs, so the first load needs an internet connection and a browser with WebGL.

## What's in it

- **3D battlefield in a gritty low-poly style**: faceted, flat-shaded models in muted survival colours under warm dusk light and haze. The angled tactical camera rotates, zooms and pans, and it follows the action. The streets have weathered concrete and brick walls with exposed rebar, wooden and ammo crates, rusted barrels, sandbags and jersey barriers, and rusting wrecked cars. There are pines and dead trees, cracked asphalt with puddles, scattered debris, and a ruined city ringing the map. Tactical overlays (move ranges, paths, detection zones, fog of war) are painted onto the floor.
- **Detailed character models**: soldiers have faces with varied skin tones, tapered limbs, plate carriers with mag pouches, belts, knee and elbow pads, gloves, boots and backpacks. Each class has its own kit:
  - Ranger: hood, scarf and a glowing Arc Blade on the back
  - Sharpshooter: boonie hat with ghillie strips, a scoped rifle with bipod, and a radio pack
  - Grenadier: armoured helmet with face shield, shoulder pads and a grenade belt
  - Specialist: headset with HUD eyepiece and a quad-rotor drone

  The Directorate troopers wear full helmets with glowing visor slits and carry breather tanks. Officers wear peaked caps and capes, Lancers have sleek helmets and coil lances, and the Warden is a hulking heavy with a glowing reactor pack.
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
