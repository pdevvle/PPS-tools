#!/bin/bash
# Bake a block into sector files and assemble the streaming page.
#   ../osm/prep_block.py writes ../osm/block_<name>.json from the region download (run it in tools/osm)
#   node bake.js ../osm/block_newriver.json ../../mockups/streaming/block
#   ./build.sh   (assembles ../../mockups/streaming/index.html; serve that folder over HTTP to try it)
cd "$(dirname "$0")"
OUT=../../mockups/streaming
{ printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
  cat stream-head.html sector-core.js figure-kit.js stream-main.js; printf '\n</script>\n</html>\n'; } > $OUT/index.html
echo "wrote $OUT/index.html"
