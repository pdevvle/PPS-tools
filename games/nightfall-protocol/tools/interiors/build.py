#!/usr/bin/env python3
"""Inline sites.json into the interiors mockup.

Writes ../../mockups/interiors.html (repo copy, with doctype) and, when given a
path, the Artifact fragment that starts with <title>."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'interiors.src.html')).read()
sites = open(os.path.join(HERE, 'sites.json')).read()
kit = open(os.path.join(HERE, 'kit.js')).read()
houses = open(os.path.join(HERE, 'houses.js')).read()
frag = src.replace('/*SITES*/[]', sites).replace('/*KIT*/', kit).replace('/*HOUSES*/', houses)
page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + frag + '\n</html>\n')
out = os.path.join(HERE, '..', '..', 'mockups', 'interiors.html')
open(out, 'w').write(page)
print('wrote', os.path.normpath(out), len(page), 'bytes')
if len(sys.argv) > 1:
    open(sys.argv[1], 'w').write(frag)
    print('wrote', sys.argv[1], len(frag), 'bytes')

# The reference sheet on roofs and houses reads its tables and roof drawings from houses.js.
sheet = open(os.path.join(HERE, 'sheet.src.html')).read()
import re
src_full = open(os.path.join(HERE, 'interiors.src.html')).read()
wallmat = re.search(r'const WALLMAT=\{[\s\S]*?\n\};', src_full).group(0).replace('const WALLMAT=', 'const WM2=')
stubs = 'const clamp=(x,a,b)=>Math.max(a,Math.min(b,x)); const pick=(r,a)=>a[Math.floor(r()*a.length)]; const DIRS=[[1,0],[0,1],[-1,0],[0,-1]];\n'
sfrag = sheet.replace('/*HOUSES*/', stubs + houses + '\n' + wallmat)
sout = os.path.join(HERE, '..', '..', 'mockups', 'roofs-and-houses.html')
open(sout, 'w').write('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n' + sfrag + '\n</html>\n')
print('wrote', os.path.normpath(sout), len(sfrag), 'bytes')
if len(sys.argv) > 2:
    open(sys.argv[2], 'w').write(sfrag); print('wrote', sys.argv[2])
