#!/usr/bin/env python3
"""Inline sites.json into the interiors mockup.

Writes ../../mockups/interiors.html (repo copy, with doctype) and, when given a
path, the Artifact fragment that starts with <title>."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'interiors.src.html')).read()
sites = open(os.path.join(HERE, 'sites.json')).read()
frag = src.replace('/*SITES*/[]', sites)
page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + frag + '\n</html>\n')
out = os.path.join(HERE, '..', '..', 'mockups', 'interiors.html')
open(out, 'w').write(page)
print('wrote', os.path.normpath(out), len(page), 'bytes')
if len(sys.argv) > 1:
    open(sys.argv[1], 'w').write(frag)
    print('wrote', sys.argv[1], len(frag), 'bytes')
