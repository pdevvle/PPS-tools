# Region to tactical zoom

`mockups/streaming/zoom.html` puts the region map and the streamed tactical ground in one page. It shares `mockups/streaming/block/` with the streaming prototype, so serve that folder over HTTP.

- `region-z.js` is the region map (`region-map.html`'s script) with the stage renamed, the baked block outlined, and a dive: past the closest zoom (or on a double-click, or Go tactical) it hands the point and any squad standing in the block to the tactical layer.
- `stream-z.js` is `tools/stream/stream-main.js` that starts only when entered, follows the camera when no squad came down, and climbs back to the map past its widest zoom.
- `glue-pre.js` converts between the region frame (centred on 33.945 N, 112.14 W) and the block frame (centred on New River); `glue-post.js` swaps the stages with a short fade and writes the squad's tactical position back to the map.

Assemble: `zoom-head.html`, `const REGION=<data/region/region_i17.json>;`, `glue-pre.js`, `region-z.js`, `../stream/sector-core.js`, `../stream/figure-kit.js`, `stream-z.js`, `glue-post.js`, then close the script.

## Combat demonstration

`combat.js` is spliced into `stream-z.js` just before its frame loop and shares its scope (movement grid, heights, figures, camera). One encounter: three raiders round the fire in the New River bridge undercroft. Raiders see 16 m in a 130° cone (5 m all round), drawn as red fans; the squad spots them at 30 m with line of sight. Whoever sees first decides the opening: the squad gets a first strike (one free shot each, +10 aim, raiders without cover), or the raiders scramble into cover before your first turn. Then turns on the 2 m grid: two actions, 12 effective metres per action so terrain speed shapes the range (blue one action, amber two), shoot ends the turn, overwatch takes a −15 reaction shot, hunker doubles cover. Walls, buildings, piers and steep ground are full cover; saguaros, palo verdes and boulders half; no cover toward the shooter means flanked (40% crit). +15 aim from 2 m higher ground. Ink shows state: concealed blue while undetected, gold selected, blue overwatch, red wounded.
