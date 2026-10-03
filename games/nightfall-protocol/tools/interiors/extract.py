#!/usr/bin/env python3
"""Cut the test buildings for the interiors mockup out of the baked New River block
and the Anthem town centre sector.

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

for s in sites:
    s['area'] = 'New River'

# ---- Anthem town centre (data/sectors/sector_anthem.json): strip malls hold several tenants,
# so every point of interest inside a footprint is kept as a tenant.
ANTHEM = os.path.join(HERE, '..', '..', 'data', 'sectors', 'sector_anthem.json')
A_PICKS = [
    (15, 'Safeway strip: a supermarket anchor and eight smaller tenants'),
    (3, 'Strip of six: jeweller, Subway, two restaurants, Baskin-Robbins, a vet'),
    (5, "McDonald's"),
    (9, 'Starbucks'),
    (17, 'MidFirst Bank'),
    (10, 'Work Hard Play Hard Marketing: offices'),
    (18, 'Ace Hardware'),
    (61, 'Grease Monkey: auto service'),
    (22, 'Circle K fuel canopy'),
    (8, 'Circle K store'),
    (4, 'Legends Bar and Grill, KOBE Hotpot and Ramen'),
    (23, "Supercuts, Filiberto's Mexican Restaurant"),
]
ROAD_W = {'secondary': 13, 'tertiary': 10, 'residential': 8, 'secondary_link': 7, 'tertiary_link': 7, 'service': 5, 'path': 2, 'footway': 2}

def pip(x, y, P):
    c = False; j = len(P) - 1
    for i in range(len(P)):
        xi, yi = P[i]; xj, yj = P[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c

A = json.load(open(ANTHEM))
for i, note in A_PICKS:
    b = A['buildings'][i]
    pts = b['pts']
    cx = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)
    tenants = [{'p': p['p'], 'what': p['what'], 'loot': p['kind'], 'name': p['name']} for p in A['pois'] if pip(p['p'][0], p['p'][1], pts)]
    site = {'id': f'anthem/centre/{i}', 'area': 'Anthem', 'block': 'anthem', 'sector': [0, 0], 'index': i, 'note': note,
            'pts': pts, 'type': b.get('type'), 'levels': b.get('levels'), 'height': b.get('height'),
            'name': b.get('name'), 'loot': b.get('loot'), 'what': b.get('what'), 'house': False, 'tenants': tenants}
    if len(tenants) == 1:
        t = tenants[0]
        site['name'] = site['name'] or t['name']; site['what'] = site['what'] or t['what']; site['loot'] = site['loot'] or t['loot']
    roads = []
    for rd in A['roads']:
        if min(seg_dist((cx, cz), rd['pts'][k], rd['pts'][k + 1]) for k in range(len(rd['pts']) - 1)) < REACH + 40:
            roads.append({'cls': rd['cls'], 'name': rd.get('name') or '', 'w': ROAD_W.get(rd['cls'], 6),
                          'drive': rd['cls'] not in ('path', 'footway'), 'pts': [[round(x, 1), round(z, 1)] for x, z in rd['pts']]})
    walls = []
    for w in A['barriers']:
        for k in range(len(w['pts']) - 1):
            a, c = w['pts'][k], w['pts'][k + 1]
            if math.hypot((a[0] + c[0]) / 2 - cx, (a[1] + c[1]) / 2 - cz) < REACH:
                walls.append([a[0], a[1], c[0], c[1], 1.8, .2, 0])
    site['roads'] = roads; site['walls'] = walls; site['centre'] = [round(cx, 2), round(cz, 2)]
    sites.append(site)

# ---- Buildings outside the baked sector, cached from the OSM API by fetch_osm.py.
# 42015 North Venture Drive is tagged building=house in OSM with no level count; it is a
# multi-storey office block, so the mockup builds it as three storeys of offices (assumed).
EXTRA = os.path.join(HERE, 'osm_extra.json')
if os.path.exists(EXTRA):
    for x in json.load(open(EXTRA)):
        pts = x['pts']
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[1] for p in pts) / len(pts)
        roads = []
        for rd in x['roads']:
            if min(seg_dist((cx, cz), rd['pts'][k], rd['pts'][k + 1]) for k in range(len(rd['pts']) - 1)) < REACH + 60:
                roads.append({'cls': rd['cls'], 'name': rd['name'], 'w': ROAD_W.get(rd['cls'], 6),
                              'drive': rd['cls'] not in ('path', 'footway'), 'pts': rd['pts']})
        t = x['tags']
        sites.append({'id': f"anthem/osm/{x['way']}", 'area': 'Anthem', 'block': 'anthem', 'sector': [0, 0], 'index': x['way'], 'note': x['note'] + ' (tagged building=' + t.get('building', '?') + ' in OSM, built here as offices)',
                      'pts': pts, 'type': 'commercial', 'levels': 3, 'levelsAssumed': True, 'height': None,
                      'name': t.get('name') or (t.get('addr:housenumber', '') + ' N Venture Dr offices'), 'loot': None, 'what': '', 'house': False,
                      'tenants': [], 'roads': roads, 'walls': [], 'water': x['water'], 'centre': [round(cx, 2), round(cz, 2)]})

out = os.path.join(HERE, 'sites.json')
json.dump(sites, open(out, 'w'), separators=(',', ':'))
print(out, os.path.getsize(out), 'bytes')
for s in sites: print(' ', s['id'], s['name'], s['what'], len(s.get('tenants') or []), 'tenants', len(s['roads']), 'roads')
