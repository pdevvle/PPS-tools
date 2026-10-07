#!/usr/bin/env python3
"""Assemble the interior combat demonstration.

Inlines the interiors generator and renderer (sliced out of tools/interiors/interiors.src.html, which belongs to the
interiors topic and is not edited here), FigureKit, the combat rules, the free-space world and the demo script into
demo.src.html. Writes ../../mockups/combat-interior.html (repo copy, with doctype) and, when given a path, the
Artifact fragment that starts with <title>."""
import os, sys, subprocess, json
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..')
slices = json.loads(subprocess.check_output(['node', '-e',
    "const {read}=require(process.argv[1]); process.stdout.write(JSON.stringify(read()))",
    os.path.join(HERE, 'interiors-slice.js')]))
rd = lambda *p: open(os.path.join(*p)).read()
page = rd(HERE, 'demo.src.html')
for key, val in [('/*FIGUREKIT*/', rd(TOOLS, 'stream', 'figure-kit.js')), ('/*MOTION*/', rd(TOOLS, 'motion', 'motion.js')),
                 ('/*INTERIORS_GEN*/', slices['gen']), ('/*INTERIORS_RENDER*/', slices['render']), ('/*INTERIORS_PHYS*/', slices['phys']),
                 ('/*RULES*/', rd(HERE, 'rules.js')), ('/*WORLD*/', rd(HERE, 'space.js')), ('/*TESTMAP*/', rd(HERE, 'testmap.js')), ('/*ROOF*/', rd(HERE, 'roof.js')),
                 ('/*DEMO*/', rd(HERE, 'demo-script.js'))]:
    assert key in page, key
    page = page.replace(key, val)
frag = page
full = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + frag + '\n</html>\n')
out = os.path.join(HERE, '..', '..', 'mockups', 'combat-interior.html')
open(out, 'w').write(full)
print('wrote', os.path.normpath(out), len(full), 'bytes')
if len(sys.argv) > 1:
    open(sys.argv[1], 'w').write(frag)
    print('wrote', sys.argv[1], len(frag), 'bytes')
