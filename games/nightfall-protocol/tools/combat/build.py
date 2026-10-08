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
wrap = lambda f: ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + f + '\n</html>\n')
# the playable page, and a debug copy: no fog, raiders' sight always drawn, lines of fire, and a panel of switches
frag = page.replace('<!--DEBUGFLAG-->', '').replace('<!--DEBUGPANEL-->', '')
dbg = (page.replace('<title>Nightfall Interior Combat</title>', '<title>Nightfall Combat Debug</title>')
           .replace('<!--DEBUGFLAG-->', '<script>window.COMBAT_DEBUG=true;</script>')
           .replace('<!--DEBUGPANEL-->', '<script>\n' + rd(HERE, 'debug.js') + '\n</script>'))
assert 'COMBAT_DEBUG' in dbg and 'Combat Debug' in dbg
for name, f in [('combat-interior.html', frag), ('combat-interior-debug.html', dbg)]:
    out = os.path.join(HERE, '..', '..', 'mockups', name)
    open(out, 'w').write(wrap(f))
    print('wrote', os.path.normpath(out), len(wrap(f)), 'bytes')
# Artifact fragments (start with <title>): argv[1] the page, argv[2] the debug copy
for path, f in zip(sys.argv[1:3], [frag, dbg]):
    open(path, 'w').write(f)
    print('wrote', path, len(f), 'bytes')
