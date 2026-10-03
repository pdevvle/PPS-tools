#!/bin/bash
# Assemble the zoom page: the region map and the streamed tactical ground with the combat demonstration.
#   ./build.sh   (writes ../../mockups/streaming/zoom.html; serve that folder over HTTP, it reads block/)
cd "$(dirname "$0")"
OUT=../../mockups/streaming/zoom.html
{ printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
  cat zoom-head.html; printf 'const REGION='; cat ../../data/region/region_i17.json; printf ';\n'
  cat glue-pre.js ../region/campaign.js ../region/region-main.js ../stream/sector-core.js ../stream/figure-kit.js ../motion/motion.js stream-z.js glue-post.js; printf '\n</script>\n</html>\n'; } > $OUT
echo "wrote $OUT"
