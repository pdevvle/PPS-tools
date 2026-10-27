#!/bin/bash
# Assemble the region map pages from their parts:
#   ../../mockups/region-map.html       region-head.html + the region data + campaign.js + region-main.js
#   ../../mockups/streaming/zoom.html   the same map half inside the zoom page, built by ../zoom/build.sh
# Run tools/region/test.js for the campaign rules (node test.js).
cd "$(dirname "$0")"
DATA=../../data/region/region_i17.json
open_html(){ printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'; }
close_html(){ printf '\n</script>\n</html>\n'; }
{ open_html; cat region-head.html; printf 'const REGION='; cat $DATA; printf ';\n'; cat campaign.js region-main.js; close_html; } > ../../mockups/region-map.html
echo "wrote mockups/region-map.html"
../zoom/build.sh
