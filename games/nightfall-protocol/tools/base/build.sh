#!/bin/bash
# Assemble the ranch prototype into ../../mockups/base.html. The site data is inlined, so it opens straight from disk.
#   python3 cut_site.py   (re-cuts ../../data/base/ranch_site.json from the baked block when the bake changes)
#   node test.js          (checks the rules)
#   ./build.sh
# The published Artifact is the same page without the first two lines (doctype and head).
cd "$(dirname "$0")"
OUT=../../mockups/base.html
body(){ cat base-head.html; printf 'const RANCH_SITE='; cat ../../data/base/ranch_site.json; printf ';\n'; cat ../stream/figure-kit.js ../motion/motion.js ranch-core.js ranch-main.js; printf '</script>\n'; }
{ printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'; body; printf '</html>\n'; } > $OUT
echo "wrote $OUT ($(wc -c < $OUT) bytes)"
