#!/bin/bash
# Assemble the motion lab into ../../mockups/motion-lab.html. It needs no data files, so it opens straight from disk.
# The published Artifact is the same page without the first two lines (doctype and head).
cd "$(dirname "$0")"
OUT=../../mockups/motion-lab.html
body(){ cat lab-head.html ../stream/figure-kit.js motion.js lab.js; printf '</script>\n'; }
{ printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'; body; printf '</html>\n'; } > $OUT
echo "wrote $OUT"
