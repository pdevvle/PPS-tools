#!/usr/bin/env python3
"""Cut the test buildings for the interiors mockup out of the baked New River block.

Writes sites.json next to this file: each building's footprint, its identity
(block, sector, index), what the bake knows about it, plus the roads and yard
walls within 60 m so the generator can find the street and the yard.
Positions stay in block metres. Data: (c) OpenStreetMap contributors, ODbL.
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK = os.path.join(HERE, '..', '..', 'mockups', 'streaming', 'block')

# (sector, building index, note)
PICKS = [
    ((2, 2), 0, 'Roadrunner: restaurant, 19-point footprint'),
    ((2, 2), 31, 'Ranch house, L-shaped, axis aligned'),
    ((2, 2), 14, 'Ranch house, L-shaped, turned about 45 degrees'),
    ((2, 2), 4, 'Lucky Mane Co.: small shop, plain rectangle'),
]
REACH = 60

def seg_dist(p, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dz * dz or 1
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / L))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dz - p[1])

sites = []
for (c, r), i, note in PICKS:
    S = json.load(open(os.path.join(BLOCK, f's_{c}_{r}.json')))
    b = S['buildings'][i]
    pts = b['pts']
    cx = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)
    site = {'id': f'newriver/{c}_{r}/{i}', 'block': 'newriver', 'sector': [c, r], 'index': i, 'note': note,
            'pts': pts, 'type': b.get('type'), 'levels': b.get('levels'), 'height': b.get('height'),
            'name': b.get('name'), 'loot': b.get('loot'), 'what': b.get('what'), 'house': bool(b.get('house'))}
    # The bake keeps shop tags on a point of interest; copy it onto the building when it sits on it.
    for p in S['pois']:
        if math.hypot(p['p'][0] - cx, p['p'][1] - cz) < 20:
            site['loot'] = site['loot'] or p.get('kind')
            site['what'] = site['what'] or p.get('what')
    roads = []
    for rd in S['roads']:
        if not rd.get('drive') and rd['cls'] not in ('pedestrian', 'footway'):
            continue
        if min(seg_dist((cx, cz), rd['pts'][k], rd['pts'][k + 1]) for k in range(len(rd['pts']) - 1)) < REACH + 40:
            roads.append({'cls': rd['cls'], 'name': rd.get('name') or '', 'w': rd['w'], 'drive': rd.get('drive', False),
                          'pts': [[round(x, 1), round(z, 1)] for x, z in rd['pts']]})
    walls = [w for w in S['walls'] if math.hypot((w[0] + w[2]) / 2 - cx, (w[1] + w[3]) / 2 - cz) < REACH]
    site['roads'] = roads
    site['walls'] = walls
    site['centre'] = [round(cx, 2), round(cz, 2)]
    sites.append(site)

out = os.path.join(HERE, 'sites.json')
json.dump(sites, open(out, 'w'), separators=(',', ':'))
print(out, os.path.getsize(out), 'bytes', [(s['id'], s['name'], s['loot'], s['what'], len(s['roads']), len(s['walls'])) for s in sites])
