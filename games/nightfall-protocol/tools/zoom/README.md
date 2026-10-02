# Region to tactical zoom

`mockups/streaming/zoom.html` puts the region map and the streamed tactical ground in one page. It shares `mockups/streaming/block/` with the streaming prototype, so serve that folder over HTTP.

- `region-z.js` is the region map (`region-map.html`'s script) with the stage renamed, the baked block outlined, and a dive: past the closest zoom (or on a double-click, or Go tactical) it hands the point and any squad standing in the block to the tactical layer.
- `stream-z.js` is `tools/stream/stream-main.js` that starts only when entered, follows the camera when no squad came down, and climbs back to the map past its widest zoom.
- `glue-pre.js` converts between the region frame (centred on 33.945 N, 112.14 W) and the block frame (centred on New River); `glue-post.js` swaps the stages with a short fade and writes the squad's tactical position back to the map.

Assemble: `zoom-head.html`, `const REGION=<data/region/region_i17.json>;`, `glue-pre.js`, `region-z.js`, `../stream/sector-core.js`, `../stream/figure-kit.js`, `stream-z.js`, `glue-post.js`, then close the script.
