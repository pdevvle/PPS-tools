# Brief: combat

Read `00-foundation.md` first.

## Goal

Turn the combat demonstration into the game's combat layer: real-time exploration on the streamed ground that folds into XCOM-style turns the moment either side spots the other, then folds back out when the fight ends.

## Where it stands

- `tools/zoom/combat.js` (spliced into `tools/zoom/stream-z.js` before its frame loop; it shares that scope). Playable in `mockups/streaming/zoom.html` and the Corridor Zoom artifact: dive into the New River block, walk the squad down the wash toward the bridge, and three raiders round a fire in the undercroft give contact.
- What works: raider vision cones; contact prompt with time slowed (engage with first strike, or hold back); being spotted makes raiders scramble to cover first; turns with two actions; blue and amber reach from a Dijkstra over the 2 m grid using terrain speeds; shoot with hit odds; overwatch reaction shots; hunker; simple raider AI (cover-seeking move, shoot when the odds are 40% or better, else overwatch); damage popups and tracers; win (survivors return to exploration, bodies stay) and loss; squad size written back to the region map on exit; leaving the ground mid-fight is blocked.
- The original game (`index.html`) has a much richer XCOM ruleset (classes, grenades, hacking, first-person overwatch, campaign). Mine it for rules and feel; its tile and data model doesn't match the real-ground grid.

## Decisions (keep)

- Combat happens on the same real ground and the same 2 m movement grid; no separate battle map.
- Whoever sees first gets the initiative; the squad's first strike is a free shot each.
- Cover is derived from what is really there (walls, buildings, piers, steep ground full; saguaros, palo verdes, boulders half). Terrain speed shapes reach.
- Character state shows in the ink stroke colour (see foundation).

## Interfaces

- Uses from the tactical runtime: `cellOf`, `kindG` (movement kinds), `nodeSpeed`, `nearestPassable`, `heightAt`, `deckAt`, the sector `data.plants`, `figs`, `squad`, `scene`, `cam`, `target`. Hooks it exposes: `CB.frame(dt,now)`, `CB.click(hit)`, `CB.hover(hit)`, `CB.onBuilt(sector)`, `CB.onDropped(sector)`, `CB.active`, `CB.prompt`.
- Figures and poses come from FigureKit (`models.md`, `animation.md`). Ask those topics for weapon models and combat animations rather than building final ones here.

## Known gaps

- Fighting under a bridge: the deck hides units from the camera. Needs a cutaway (fade or hide what is above the focus).
- Decks are ignored in combat (ground layer only); half-height parapets don't count as cover or block shots.
- The action bar covers much of the view on smaller screens.
- One hard-coded encounter. Needs encounter data: who is where, patrols, pods, alertness, reinforcements, and how encounters come from the strategic map.
- No classes, weapons, ammo, grenades, injuries that persist, morale (the panicked ink exists), or loot after a fight.
- Raiders' AI is greedy per unit; no pod tactics, flanking intent or retreat.
- Line of sight is a coarse sample along a line at 1.5 m; no partial visibility.
- No fighting indoors yet: interiors (walls, doors, windows, furniture cover) come from `interiors.md`.

## First tasks

1. Move `combat.js` out of the splice into its own module with a clear interface to the tactical runtime.
2. Camera cutaway for decks and roofs over the focused unit.
3. Encounter data format (pods, patrols, alert states) and two or three encounters placed in the New River block.
4. Weapons and classes: start with the original game's four (Ranger, Sharpshooter, Grenadier, Specialist) adapted to survivors.
5. Persist wounds and deaths back to the squad (the region map shows people per squad).

## Out of scope

The ground itself, streaming and pathing (`tactical-maps.md`); figure geometry and clothing (`models.md`); motion (`animation.md`); where encounters come from on the map (`strategy-map.md`, agree a format with them).
