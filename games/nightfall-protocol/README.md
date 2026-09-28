# Nightfall Protocol

A turn-based squad tactics game inspired by XCOM 2. It is one self-contained HTML file with no build step. Open `index.html` in a browser to play.

## What's in it

- **4-soldier squad**: Ranger (shotgun + Arc Blade slash), Sharpshooter (sniper with squadsight + pistol), Grenadier (cannon + grenade launcher), Specialist (rifle + aid drone, remote hacking).
- **Two actions per turn**: move within the blue range (1 action) or dash into the amber range (2). Firing ends the soldier's turn.
- **Cover and flanking**: half cover gives −20 to enemy aim and full cover −40. If no cover faces the shooter, the unit is flanked and the shot gets +50% crit chance. Shield icons show cover at the hovered tile, and FLANK tags show which enemies you would flank from there.
- **Overwatch, hunker down, reload, grenades**: explosives destroy cover and shred armor.
- **Concealment**: the squad starts hidden. Red tiles mark where patrols would detect you. Ambush a pod with overwatch.
- **Mission timer**: hack the relay within 12 turns. Reinforcements drop two turns after the hack. Then kill every hostile or evacuate.
- **Enemy AI**: patrolling pods scramble to cover when they activate. They pick firing positions based on cover and flanking, and they overwatch when they have no shot. Stun Lancers rush your soldiers.
- **Campaign**: survivors earn XP, ranks and nicknames. The dead go on the memorial and rookies replace them. Difficulty rises with each mission. Progress is saved in `localStorage`.

## Controls

Click a soldier to select, then click a tile to move. `1`–`8` pick actions, `Tab` cycles soldiers or targets, `Enter` confirms, `Esc` cancels, `E` ends the turn. On touch devices, tap a tile once to preview the move and again to confirm it.
